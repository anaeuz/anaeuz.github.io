#!/usr/bin/env python3
"""Coleta os dados da API do Instagram e grava data/instagram.json.

Uso:  IG_ACCESS_TOKEN=... python3 scripts/coletar_instagram.py

O token nunca é gravado no JSON nem impresso no log.
"""
import json
import os
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PASTA_DADOS = os.path.join(RAIZ, "data")
TOKEN = os.environ.get("IG_ACCESS_TOKEN", "").strip()
VERSAO = os.environ.get("IG_API_VERSION", "v24.0")
BASE = "https://graph.instagram.com/" + VERSAO
DIA = 86400

DIAS_RECENTES = 90        # posts mais novos que isso têm as métricas atualizadas sempre
DIAS_CACHE = 7            # posts antigos são atualizados uma vez por semana
DIAS_ENGAJAMENTO = 60     # janela usada na taxa de engajamento
MIN_POSTS = 12            # mesmo postando pouco, o engajamento usa pelo menos os 12 últimos
MAX_MIDIAS = 500
MAX_POSTS_POR_EXECUCAO = 150  # protege o limite de ~200 chamadas/hora
QTD_DESTAQUES = 8

CAMPOS_PERFIL = "user_id,username,name,biography,profile_picture_url,followers_count,follows_count,media_count,website"
CAMPOS_MIDIA = "id,caption,media_type,media_product_type,permalink,thumbnail_url,media_url,timestamp,like_count,comments_count"
METRICAS_FEED = "views,reach,likes,comments,shares,saved,total_interactions"
METRICAS_REELS = METRICAS_FEED + ",ig_reels_avg_watch_time"
ORDEM_IDADE = ["13-17", "18-24", "25-34", "35-44", "45-54", "55-64", "65+"]


class ErroApi(Exception):
    pass


def api(endpoint, params=None):
    """Chama a Graph API. `endpoint` pode ser um caminho ou a URL de paginação."""
    if endpoint.startswith("http"):
        url = endpoint
    else:
        query = dict(params or {})
        query["access_token"] = TOKEN
        url = BASE + "/" + endpoint + "?" + urllib.parse.urlencode(query)
    nome = urllib.parse.urlparse(url).path  # nunca inclui o token
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        try:
            msg = json.load(e).get("error", {}).get("message", str(e))
        except Exception:
            msg = str(e)
        raise ErroApi("{}: {}".format(nome, msg))
    except urllib.error.URLError as e:
        raise ErroApi("{}: {}".format(nome, e.reason))


FALHAS_CRITICAS = []  # falhas que fazem a Action ficar vermelha (e o GitHub mandar e-mail)


def tentar(descricao, fn, critico=False):
    try:
        return fn()
    except ErroApi as e:
        print("⚠️  {} — {}".format(descricao, e), file=sys.stderr)
        if critico:
            FALHAS_CRITICAS.append(descricao)
        return None


def valores_insight(resposta):
    out = {}
    for item in (resposta or {}).get("data", []):
        if "total_value" in item:
            out[item["name"]] = item["total_value"].get("value", 0)
        elif item.get("values"):
            out[item["name"]] = item["values"][0].get("value", 0)
    return out


def resultados_breakdown(resposta):
    try:
        return resposta["data"][0]["total_value"]["breakdowns"][0]["results"]
    except (TypeError, KeyError, IndexError):
        return []


def data_iso(ts):
    return datetime.strptime(ts[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)


def coletar_midias():
    """Lista todos os posts da conta (só a listagem, sem métricas)."""
    midias = []
    pagina = api("me/media", {"fields": CAMPOS_MIDIA, "limit": 50})
    while pagina:
        midias.extend(pagina.get("data", []))
        proxima = pagina.get("paging", {}).get("next")
        if not proxima or len(midias) >= MAX_MIDIAS:
            break
        pagina = api(proxima)
    return midias[:MAX_MIDIAS]


def insights_midia(m, reels):
    """Busca as métricas do post. Posts antigos podem não aceitar todas, então tenta listas menores."""
    tentativas = [METRICAS_REELS if reels else METRICAS_FEED, METRICAS_FEED,
                  "reach,likes,comments,shares,saved,total_interactions"]
    for i, lista in enumerate(tentativas):
        try:
            v = valores_insight(api(m["id"] + "/insights", {"metric": lista}))
        except ErroApi as e:
            if i == len(tentativas) - 1:
                print("⚠️  insights do post {} — {}".format(m["id"], e), file=sys.stderr)
            continue
        if "views" not in v:
            extra = tentar("views do post " + m["id"],
                           lambda: api(m["id"] + "/insights", {"metric": "views"}))
            v.update(valores_insight(extra))
        return v
    return {}


def detalhar_todas(midias):
    """Métricas de todos os posts. Os recentes são sempre atualizados; os antigos vêm do
    cache e só são buscados de novo a cada DIAS_CACHE dias, para respeitar o limite da API."""
    caminho = os.path.join(PASTA_DADOS, "cache_posts.json")
    try:
        with open(caminho, encoding="utf-8") as f:
            cache = json.load(f)
    except (OSError, ValueError):
        cache = {}
    agora = datetime.now(timezone.utc)
    corte_recente = agora - timedelta(days=DIAS_RECENTES)
    novo_cache, posts, chamadas = {}, [], 0
    for m in midias:
        item = cache.get(m["id"])
        recente = data_iso(m["timestamp"]) >= corte_recente
        vencido = not item or (agora - data_iso(item["coletadoEm"])).days >= DIAS_CACHE
        if (recente or vencido) and chamadas < MAX_POSTS_POR_EXECUCAO:
            chamadas += 1
            item = {"coletadoEm": agora.isoformat(timespec="seconds"), "post": detalhar_midia(m)}
        if item:
            novo_cache[m["id"]] = item
            post = dict(item["post"])
        else:
            post = detalhar_midia(m, buscar_insights=False)  # entra no cache na próxima execução
        # o link da miniatura expira, então sempre usa o da listagem atual
        post["thumb"] = m.get("thumbnail_url") or m.get("media_url")
        posts.append(post)
    with open(caminho, "w", encoding="utf-8") as f:
        json.dump(novo_cache, f, ensure_ascii=False)
    print("ℹ️  {} posts na conta, {} atualizados nesta execução.".format(len(midias), chamadas))
    return posts


def detalhar_midia(m, buscar_insights=True):
    reels = m.get("media_product_type") == "REELS"
    v = insights_midia(m, reels) if buscar_insights else {}
    likes = v.get("likes", m.get("like_count", 0)) or 0
    comentarios = v.get("comments", m.get("comments_count", 0)) or 0
    salvos = v.get("saved", 0) or 0
    compart = v.get("shares", 0) or 0
    legenda = (m.get("caption") or "").strip().split("\n")[0]
    if len(legenda) > 90:
        legenda = legenda[:87].rstrip() + "…"
    if reels:
        tipo = "Reels"
    elif m.get("media_type") == "CAROUSEL_ALBUM":
        tipo = "Carrossel"
    else:
        tipo = "Post"
    tempo = v.get("ig_reels_avg_watch_time")
    return {
        "id": m["id"],
        "tipo": tipo,
        "legenda": legenda,
        "permalink": m.get("permalink"),
        "thumb": m.get("thumbnail_url") or m.get("media_url"),
        "data": m["timestamp"],
        "views": v.get("views", 0) or 0,
        "alcance": v.get("reach", 0) or 0,
        "likes": likes,
        "comentarios": comentarios,
        "salvos": salvos,
        "compartilhamentos": compart,
        "interacoes": v.get("total_interactions") or (likes + comentarios + salvos + compart),
        "tempoMedioSeg": round(tempo / 1000, 1) if tempo else None,
    }


def insights_conta(desde, ate):
    janela = {"period": "day", "metric_type": "total_value", "since": desde, "until": ate}
    totais = valores_insight(tentar("insights da conta", lambda: api(
        "me/insights", dict(janela, metric="reach,views,accounts_engaged,total_interactions")), critico=True))
    totais.update(valores_insight(tentar("envios da conta", lambda: api(
        "me/insights", dict(janela, metric="shares")))))

    nao_seguidores = None
    por_tipo = resultados_breakdown(tentar("alcance por tipo de seguidor", lambda: api(
        "me/insights", dict(janela, metric="reach", breakdown="follow_type"))))
    soma = sum(r.get("value", 0) for r in por_tipo)
    if soma:
        nao = sum(r.get("value", 0) for r in por_tipo if "NON_FOLLOWER" in r.get("dimension_values", []))
        nao_seguidores = round(nao / soma * 100, 1)

    novos = None
    serie = tentar("novos seguidores", lambda: api(
        "me/insights", {"metric": "follower_count", "period": "day", "since": desde, "until": ate}))
    if serie and serie.get("data"):
        novos = sum(p.get("value", 0) for p in serie["data"][0].get("values", []))

    return totais, nao_seguidores, novos


def demografia(breakdown):
    r = tentar("público por " + breakdown, critico=True, fn=lambda: api("me/insights", {
        "metric": "follower_demographics", "period": "lifetime", "metric_type": "total_value",
        "timeframe": "this_month", "breakdown": breakdown,
    }))
    return [(", ".join(x.get("dimension_values", [])), x.get("value", 0)) for x in resultados_breakdown(r)]


def montar_publico():
    genero = demografia("gender")
    idade = demografia("age")
    cidades = demografia("city")
    paises = demografia("country")
    base = sum(v for _, v in genero) or sum(v for _, v in idade)
    if not base:
        return {"disponivel": False, "motivo": "indisponivel"}

    def p(v):
        return round(v / base * 100, 1)

    g = dict(genero)
    idade_ord = sorted(idade, key=lambda x: ORDEM_IDADE.index(x[0]) if x[0] in ORDEM_IDADE else 99)
    return {
        "disponivel": True,
        "base": base,
        "genero": {"F": p(g.get("F", 0)), "M": p(g.get("M", 0)), "U": p(g.get("U", 0))},
        "idade": [{"faixa": k, "pct": p(v)} for k, v in idade_ord],
        "cidades": [{"nome": k, "pct": p(v)} for k, v in sorted(cidades, key=lambda x: -x[1])[:5]],
        "paises": [{"codigo": k, "pct": p(v)} for k, v in sorted(paises, key=lambda x: -x[1])[:5]],
    }


def atualizar_historico(seguidores):
    caminho = os.path.join(PASTA_DADOS, "historico.json")
    try:
        with open(caminho, encoding="utf-8") as f:
            historico = json.load(f)
    except (OSError, ValueError):
        historico = []
    hoje = datetime.now(timezone.utc).date().isoformat()
    historico = [h for h in historico if h["data"] != hoje]
    historico.append({"data": hoje, "seguidores": seguidores})
    historico = sorted(historico, key=lambda h: h["data"])[-400:]
    with open(caminho, "w", encoding="utf-8") as f:
        json.dump(historico, f, ensure_ascii=False, indent=1)
    return historico


def crescimento(historico, seguidores, novos_30d):
    limite = (datetime.now(timezone.utc).date() - timedelta(days=30)).isoformat()
    antigos = [h for h in historico if h["data"] <= limite]
    if antigos and antigos[-1]["seguidores"]:
        antes = antigos[-1]["seguidores"]
        return {"percentual": round((seguidores - antes) / antes * 100, 1),
                "novos": seguidores - antes, "fonte": "historico"}
    if novos_30d:
        antes = max(seguidores - novos_30d, 1)
        return {"percentual": round(novos_30d / antes * 100, 1), "novos": novos_30d, "fonte": "api"}
    return None


def media(valores):
    valores = [v for v in valores if v is not None]
    return round(sum(valores) / len(valores), 2) if valores else None


def main():
    if not TOKEN:
        sys.exit("Defina a variável IG_ACCESS_TOKEN.")
    os.makedirs(PASTA_DADOS, exist_ok=True)

    perfil = api("me", {"fields": CAMPOS_PERFIL})
    seguidores = perfil.get("followers_count", 0)

    posts = detalhar_todas(coletar_midias())

    agora = int(time.time())
    totais, nao_seguidores, novos = insights_conta(agora - 30 * DIA + 3600, agora)

    corte_eng = datetime.now(timezone.utc) - timedelta(days=DIAS_ENGAJAMENTO)
    recentes = [p for p in posts if data_iso(p["data"]) >= corte_eng]
    if len(recentes) < MIN_POSTS:
        recentes = posts[:MIN_POSTS]
    engajamento = media([p["interacoes"] / p["alcance"] * 100 for p in recentes if p["alcance"]])
    reels = [p for p in recentes if p["tipo"] == "Reels"]

    # "views típicas": mediana dos Reels recentes, que não é distorcida por um viral
    corte_rec = datetime.now(timezone.utc) - timedelta(days=DIAS_RECENTES)
    views_reels_rec = [p["views"] for p in posts
                       if p["tipo"] == "Reels" and p["views"] and data_iso(p["data"]) >= corte_rec]
    recorde = max((p for p in posts if p["tipo"] == "Reels"), key=lambda p: p["views"], default=None)
    envios30d = totais.get("shares")
    if envios30d is None:  # se a conta não informar, soma os envios dos posts publicados no período
        corte_30 = datetime.now(timezone.utc) - timedelta(days=30)
        envios30d = sum(p["compartilhamentos"] for p in posts if data_iso(p["data"]) >= corte_30)

    historico = atualizar_historico(seguidores)

    dados = {
        "exemplo": False,
        "atualizadoEm": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "perfil": {k: perfil.get(k) for k in
                   ("username", "name", "biography", "profile_picture_url",
                    "followers_count", "follows_count", "media_count", "website")},
        "resumo": {
            "seguidores": seguidores,
            "crescimento30d": crescimento(historico, seguidores, novos),
            "alcance30d": totais.get("reach"),
            "alcanceNaoSeguidoresPct": nao_seguidores,
            "views30d": totais.get("views"),
            "contasEngajadas30d": totais.get("accounts_engaged"),
            "interacoes30d": totais.get("total_interactions"),
            "engajamentoMedio": round(engajamento, 2) if engajamento is not None else None,
            "mediaInteracoesPost": media([p["interacoes"] for p in recentes]),
            "mediaViewsReels": media([p["views"] for p in reels]),
            "medianaViewsReels": statistics.median(views_reels_rec) if views_reels_rec else None,
            "reelsNaMediana": len(views_reels_rec),
            "recordeViews": recorde["views"] if recorde else None,
            "recordePermalink": recorde["permalink"] if recorde else None,
            "envios30d": envios30d,
            "postsAnalisados": len(recentes),
        },
        "publico": montar_publico(),
        "destaques": sorted(posts, key=lambda p: (p["views"], p["alcance"]), reverse=True)[:QTD_DESTAQUES],
        "ultimoReel": next((p for p in posts if p["tipo"] == "Reels"), None),
        # todos os posts, para o site achar os que forem citados no site.config.json
        "posts": [{k: p[k] for k in ("id", "tipo", "legenda", "permalink", "thumb", "data", "views",
                                     "likes", "comentarios", "salvos", "compartilhamentos")} for p in posts],
    }

    preservar_dados_anteriores(dados, seguidores)

    with open(os.path.join(PASTA_DADOS, "instagram.json"), "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=1)
    print("✅ @{}: {} seguidores, {} posts analisados.".format(
        perfil.get("username"), seguidores, len(posts)))
    if FALHAS_CRITICAS:
        sys.exit("❌ Falhas: {}. O site mantém os últimos valores bons.".format(", ".join(FALHAS_CRITICAS)))


def preservar_dados_anteriores(dados, seguidores):
    """Se alguma métrica falhar, mantém o último valor bom em vez de mostrar vazio no site."""
    try:
        with open(os.path.join(PASTA_DADOS, "instagram.json"), encoding="utf-8") as f:
            anterior = json.load(f)
    except (OSError, ValueError):
        return
    if anterior.get("exemplo"):
        return
    mantidos = []
    for chave, valor in dados["resumo"].items():
        if valor is None and anterior.get("resumo", {}).get(chave) is not None:
            dados["resumo"][chave] = anterior["resumo"][chave]
            mantidos.append(chave)
    if not dados["publico"].get("disponivel"):
        if seguidores < 100:
            dados["publico"]["motivo"] = "poucos_seguidores"
        elif anterior.get("publico", {}).get("disponivel"):
            dados["publico"] = anterior["publico"]
            mantidos.append("publico")
    if mantidos:
        print("ℹ️  Mantidos os valores anteriores de: " + ", ".join(mantidos))


if __name__ == "__main__":
    main()
