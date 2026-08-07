# Ownership enforcement — da implementare con l'autenticazione reale

Questo documento elenca i punti individuati durante l'hotfix di sicurezza
pre-closed-beta (`security/pre-beta-safety-hotfix`) che richiederanno un
controllo di ownership quando arriverà il sistema di account reale della
closed beta. **Non contiene alcuna modifica di comportamento**: è solo la
mappa di ciò che resta da proteggere.

## Perché non è stato implementato ora

Un controllo di ownership richiede due cose che oggi non esistono insieme:

1. Un'identità affidabile del chiamante (l'autenticazione reale arriverà con
   gli account della closed beta — fuori scope per questo hotfix).
2. Un campo "proprietario" persistito sui documenti `queries` e
   `conclusions`. **Oggi questo campo non esiste**: `create_query()` in
   `server.py` non salva alcun `user_id` sul documento, e non riceve nemmeno
   `IdentityContext` come dipendenza. Anche un utente identificato
   (header `X-User-Id`) non lascia traccia del proprio `user_id` sulla query
   che crea.

Di conseguenza non esiste oggi alcun modo, nemmeno provvisorio, di
verificare realmente "questo chiamante possiede questa risorsa" senza
introdurre un sistema di autenticazione ad-hoc — esattamente ciò che questo
hotfix ha istruzione esplicita di non fare (`NON introdurre ora un sistema
provvisorio di autenticazione che dovremo eliminare`). Fingere un controllo
basato sul solo `X-User-Id` sarebbe peggio di nessun controllo: darebbe una
falsa sensazione di sicurezza, dato che l'header è liberamente impostabile
dal chiamante.

## Endpoint che richiederanno ownership enforcement

Ciascuno è marcato nel codice con un commento `# TODO(security-ownership)`
che rimanda a questo file.

| Endpoint | File / funzione | Rischio oggi |
|---|---|---|
| `GET /api/queries/{query_id}` | `server.py::get_query` | Chiunque conosca l'ID legge il prompt di un altro utente. |
| `POST /api/queries/{query_id}/compare` | `server.py::compare_query` | Chiunque conosca l'ID può (ri)eseguire una comparazione a pagamento sulla query di un altro utente. |
| `GET /api/conclusions/{conclusion_id}` | `server.py::get_conclusion` | Chiunque conosca l'ID legge la conclusione di un altro utente. |
| `POST /api/conclusions/{conclusion_id}/translate` | `server.py::translate_conclusion` | Chiunque conosca l'ID può forzare una traduzione a pagamento sulla conclusione di un altro utente. |

Gli ID sono UUID v4, quindi non enumerabili per forza bruta in pratica; il
rischio reale è la combinazione con qualunque altro punto che elenchi o
suggerisca ID validi (vedi sotto).

## Scoperta correlata — RISOLTA (approvata dopo la consegna del report)

`GET /api/queries` (senza ID, `server.py::list_queries`) restituiva fino a
200 record — inclusa la stringa completa del prompt — di **qualunque**
utente, senza autenticazione. Non era nell'elenco esplicito dei punti da
correggere in questa patch (il frontend non lo chiama mai — verificato:
nessun riferimento in `frontend/src`), quindi era stata segnalata come
decisione da approvare invece di essere corretta d'ufficio.

**Approvata e applicata**: l'endpoint è ora protetto con
`dependencies=[Depends(require_admin)]`, lo stesso meccanismo già usato da
`/api/compare_logs`. Nessun impatto sul frontend (non lo usa).

## Cosa serve quando arriverà l'autenticazione reale

1. Aggiungere un campo `user_id` (nullable per compatibilità con dati
   storici pre-beta) ai documenti `queries` e `conclusions`, valorizzato da
   `IdentityContext` al momento della creazione.
2. Introdurre un helper centralizzato (es. `auth.assert_owns_resource(doc,
   identity)`) usato da tutti gli endpoint elencati sopra, così la regola di
   ownership vive in un solo posto invece di essere duplicata.
3. Decidere esplicitamente il comportamento per i chiamanti anonimi verso
   risorse esistenti create da un utente identificato (oggi il prodotto
   supporta un flusso anonimo completo; la policy post-auth va concordata,
   non dedotta implicitamente).
