# Mídia Kit ao vivo

Página de mídia kit com os dados do Instagram atualizados sozinhos a cada 3 horas.

```
GitHub Actions (a cada 3h) → API do Instagram → data/instagram.json → site
```

O token fica guardado como segredo no GitHub e nunca aparece no site.

## Arquivos

| Arquivo | O que é |
|---|---|
| `index.html` | A página (layout do Stitch) |
| `site.config.json` | **Seus textos**: nome, tags, manifesto, contatos, parceiros |
| `data/instagram.json` | Números do Instagram (gerado automaticamente; hoje tem dados de exemplo) |
| `data/historico.json` | Seguidores por dia, para calcular o crescimento |
| `scripts/coletar_instagram.py` | Busca os dados na API |
| `.github/workflows/` | Agendamentos da coleta e da renovação do token |

## 1. Personalizar

Edite o `site.config.json`:

- `nome`, `usuario`, `descricao`, `tags`, `manifesto`
- `fotoUrl`: foto principal. Coloque uma foto sua em `img/` e use `"img/minha-foto.jpg"`
- `logoUrl`: deixe `""` se não tiver logo
- `contato.whatsapp`: só números, com DDI e DDD (ex.: `5511987654321`)
- `selo`: frase de confiança, por exemplo sobre nota fiscal e contrato. Só preencha se for verdade
- `parceiros`: `[{"nome": "Marca X", "logoUrl": "img/marca-x.png", "link": "https://..."}]`

## 2. Ver no computador

```bash
cd ~/midia-kit
python3 -m http.server 8000
```

Abra http://localhost:8000. Não funciona abrindo o arquivo direto com duplo clique, porque o navegador bloqueia a leitura dos JSON.

## 3. Conectar o Instagram

1. Confirme que a conta é **Criador** ou **Empresa**.
2. Em developers.facebook.com, crie um app do tipo **Empresa** e adicione o produto **Instagram** com a opção "API setup with Instagram login".
3. Em **Funções do app → Testadores do Instagram**, adicione o seu @ e aceite o convite no Instagram (Configurações → Apps e sites).
4. Gere o token em **Generate access tokens**. Ele é de longa duração (60 dias).
5. Para testar no computador (opcional):
   ```bash
   IG_ACCESS_TOKEN='seu_token' python3 scripts/coletar_instagram.py
   ```

## 4. Publicar (GitHub Pages)

1. Crie um repositório no GitHub e envie esta pasta.
2. Em **Settings → Secrets and variables → Actions**, crie os segredos:
   - `IG_ACCESS_TOKEN`: o token do Instagram
   - `GH_PAT`: um token pessoal do GitHub (*fine-grained*, só este repositório, permissão **Secrets: read and write**). Ele é usado para salvar o token renovado.
3. Em **Settings → Pages**, escolha *Deploy from a branch*, a branch `main` e a pasta `/ (root)`.
4. Em **Actions → Atualizar dados do Instagram**, clique em **Run workflow** para a primeira coleta.
5. Para usar o seu domínio: em **Settings → Pages → Custom domain**, siga as instruções de DNS.

Funciona também na Vercel ou Netlify: é só importar o repositório. Cada commit de dados publica a versão nova.

## "Como eu integro marcas"

No `site.config.json`, em `integracoes`:
- `texto` e `pontos`: o seu texto e a lista com ✓.
- `exemplos`: cole o link do Reels (no Instagram: ⋯ → Copiar link), o nome do produto e uma nota.
  Pode ter mais de um. A capa e a legenda vêm sozinhas da API.

## Contador de visitas (GoatCounter)

1. Crie uma conta grátis em https://www.goatcounter.com e escolha um código (ex.: `anapaulaeuz`).
2. No `site.config.json`, preencha `"goatcounter": "anapaulaeuz"`.
3. As visitas aparecem em `https://anapaulaeuz.goatcounter.com`. Não conta as suas visitas no `localhost`.

**Para saber qual marca abriu o kit**, mande um link diferente para cada uma, com `?ref=`:
`https://seudominio.com/?ref=empresa-x`. No painel, a visita aparece com a origem `empresa-x`.

## Bom saber

- **Crescimento de seguidores**: até completar 30 dias de histórico, o site usa os novos seguidores informados pela API.
- **Público** (gênero, idade, cidades): só aparece com mais de 100 seguidores.
- **Engajamento**: interações (curtidas, comentários, salvos e compartilhamentos) ÷ alcance, média dos posts dos últimos 60 dias.
- **Formulário**: abre o e-mail de quem está preenchendo, já com a mensagem montada.
- Se a Meta mudar os nomes das métricas, os avisos aparecem no log da Action. A versão da API pode ser trocada pela variável `IG_API_VERSION`.
