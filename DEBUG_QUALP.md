# Debug QualP — Histórico de tentativas

## Problema
QualP scraper funciona local (headless=False) mas falha em Docker headless.

## Tentativas já feitas (NÃO repetir)

### ❌ Aumentar playwright_resultado_timeout_ms
- Estava em 90s, foi testado — ainda timeout
- O problema não é tempo de espera, é que div.route-table nunca aparece

### ✅ Fix Vue.js event dispatch após keyboard.type()  
- Commit: f78a3f4 (main)
- Resultado: MUDOU o erro de "nenhuma sugestão → pressionando Enter" para "timeout aguardando resultado da rota"
- Isso sugere que o autocomplete PODE estar funcionando agora

### ❌ Timeout do autocomplete panel 5000ms
- Já foi aumentado para 15000ms no main — NÃO aumentar mais

---

## Estado atual (após f78a3f4)

- Erro: "Erro inesperado: QualP: timeout aguardando resultado da rota."
- O SEL_RESULT_TABLE = "div.route-table" nunca fica visible dentro de 90s

## Próximos passos a investigar

1. **Ver debug_pre_calcular.png** — mostra se origem/destino estão preenchidos antes do CALCULAR
   - Acesse: `hub.real94.com.br/debug/screenshot/debug_pre_calcular`
2. **Ver debug_resultado.png** — mostra estado do browser quando dá timeout
   - Acesse: `hub.real94.com.br/debug/screenshot/debug_resultado`
3. **Verificar logs** — procurar "campos antes de CALCULAR" nos logs para ver os valores dos campos
4. Se campos estiverem VAZIOS → o problema é que a seleção do autocomplete não está "committando" o valor no Vue
5. Se campos estiverem PREENCHIDOS → o problema é o seletor div.route-table ou QualP está mostrando erro

## URLs de debug (após deploy)
- `https://hub.real94.com.br/debug/screenshot/debug_pre_calcular` → form antes do CALCULAR
- `https://hub.real94.com.br/debug/screenshot/debug_resultado` → browser quando timeout
