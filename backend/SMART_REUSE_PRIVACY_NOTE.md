# Smart Reuse — esposizione del prompt originale nel match

## Cosa fa oggi `POST /api/queries/match`

Il campo `match.prompt` nella risposta (`server.py::match_query`, oggetto
`match`) contiene il **testo letterale** della domanda originale associata
alla conclusione riutilizzabile trovata (`best_doc["prompt"]`), non solo la
risposta sintetizzata. Poiché il pool di conclusioni riutilizzabili è
condiviso globalmente fra tutti gli utenti (nessuno scoping per utente/
tenant — vedi audit indipendente, §5), un utente può quindi vedere la
domanda letterale posta in precedenza da un altro utente.

## Verifica: il frontend ne ha realmente bisogno

Prima di proporre qualunque rimozione sono stati controllati tutti gli usi
di `match.prompt` nel frontend e nei test:

- `frontend/src/pages/ReuseFound.jsx` (riga ~106): l'intera pagina di
  conferma del riuso mostra `"{match.prompt}"` sotto l'etichetta
  `reuse.previousQuestion`, per permettere all'utente di confrontare
  visivamente la propria domanda con quella già risposta prima di scegliere
  se riutilizzare, aggiornare o generare una risposta nuova.
- `frontend/src/pages/Results.jsx` (riga ~854): nella barra "reused/updated"
  mostra `· {t("results.previousQuestion")}: "{match.prompt}"` con la
  stessa funzione.
- `frontend/src/pages/Results.jsx` (riga ~117): `sharePrompt` viene
  inizializzato da `reuseMatch?.prompt` come fallback per il testo mostrato
  in testa alla pagina risultati in modalità riuso.
- Nessun test frontend o backend asserisce l'assenza di `match.prompt`; i
  test esistenti (`test_multilingual.py`, `backend_test.py`,
  `test_identity_auth.py`) non ne dipendono, ma nemmeno lo vietano.

**Conclusione**: il campo è realmente necessario al flusso attuale.
Rimuoverlo senza un sostituto avrebbe rotto la pagina `ReuseFound` (il cuore
della UX è proprio il confronto testuale) e la barra "reused/updated" in
`Results.jsx` — esplicitamente vietato da questa patch
("non rompere il flusso ReuseFound"). **Non è stata quindi rimossa alcuna
funzionalità.**

## Soluzione privacy-safe proposta per una fase successiva (non implementata ora)

Fuori dallo scope di questo hotfix (richiederebbe una modifica strutturale
al modello dati / al matching), ma da valutare quando arriverà il sistema
di account reale:

1. **Scoping per account**: una volta esistenti account reali, restringere
   il pool di Smart Reuse ai soli documenti creati dallo stesso account (o
   a un pool "pubblico" esplicitamente opt-in), così `match.prompt`
   apparterrebbe sempre al chiamante stesso.
2. **Se il pool condiviso resta un requisito di prodotto** (per
   massimizzare il risparmio di costo condividendo compute fra utenti su
   argomenti stabili/tecnici): sostituire il prompt letterale con un
   riassunto/parafrasi generato una sola volta al momento della creazione
   della conclusione (stesso costo del riuso, zero costo aggiuntivo in
   lettura) invece del testo originale verbatim, oppure mostrare solo la
   percentuale di similarità e il topic senza il testo.
3. In entrambi i casi la decisione è di prodotto, non solo tecnica — va
   presa esplicitamente dal team, non dedotta implicitamente da un audit di
   sicurezza.

Questo hotfix lascia il comportamento invariato e si limita a documentare
il compromesso.
