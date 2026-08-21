# Slice 2 — residui noti

**Data:** 2026-08-21
**Stato:** slice 2 completo, 18 task, 1052 test backend e 309 frontend
**Scopo:** ciò che sappiamo essere aperto. Ogni voce è stata riprodotta o verificata leggendo il
codice spedito, non dedotta dal piano.

---

## C1 — La macchina a stati dell'offerta è duplicata, e il backend la pubblica solo negli errori

`OFFER_TRANSITIONS` esiste due volte: in `packages/core/src/pigrocrm/core/documents/service.py:50`
e in `apps/web/src/features/documents/queries.ts:31`. Il frontend ne ha bisogno per decidere quali
pulsanti mostrare in `OfferStatePicker`.

Il backend **conosce** le transizioni ammesse e le comunica — ma soltanto dentro i `details` di un
errore, quando una transizione viene rifiutata (`service.py:541`, `transizioni_ammesse`). Non sono
esposte su `DocumentRead`.

Conseguenza: se un giorno il backend aggiunge una transizione, la UI **non la offrirà** e nessun test
lo dirà, perché le due tabelle non hanno alcun meccanismo che le tenga allineate. Il difetto si
manifesta come un pulsante che manca, che è il tipo di cosa che si attribuisce a una scelta di
disegno invece che a una dimenticanza.

**Cura:** aggiungere `transizioni_ammesse` a `DocumentRead` e far chiedere alla UI invece di
indovinare. È la stessa regola già applicata alle colonne dei campi custom, che vengono dallo schema
vivo e non da una lista scritta a mano.

---

## C2 — Nessun caricamento per logo e firma dell'emittente

`emitter_profile` ha `logo_key` e `firma_key`, che sono chiavi di storage per due immagini, ma non
esiste interfaccia per caricarle. Il pannello Emittente **non le mostra deliberatamente**: offrire un
campo di testo per una chiave inviterebbe a scrivere un percorso che non risolve niente.

Le due immagini oggi arrivano dagli asset dell'immagine Docker, quindi sostituirle significa
sostituire dei file nell'immagine. Funziona, ma non è configurabile come promette il resto del
profilo.

---

## C3 — Un file orfano su Google Drive può restare a tempo indefinito

Due scritture concorrenti su una chiave **nuova** possono creare due file: l'API di Drive non ha un
create-if-absent atomico. `delete` ora rimuove ogni file che porta la chiave e `put` sana i duplicati
che trova, quindi non c'è più né resurrezione né dato sbagliato restituito — ma se quella chiave non
viene mai più letta, scritta o cancellata, l'orfano resta. È igiene, non correttezza.

---

## C4 — `variabili_non_usate` può segnalare una variabile che il renderer userebbe

`describe` confronta i nomi dichiarati con i **percorsi radice**. Una variabile scritta unicamente
dentro un `{{#each}}` viene segnalata come inutilizzata, benché il renderer la risolverebbe risalendo
agli scope esterni quando l'elemento del ciclo non ha quella chiave.

È un'ambiguità inerente: staticamente non si distingue «campo della riga» da «fallback voluto sulla
radice» senza conoscere la forma degli elementi a tempo di render. Segnalata come tale invece di
essere risolta a caso.

---

## C5 — Residui minori del motore di template

- Un tag di blocco che condivide la riga fisica con del contenuto (`{{#if x}}foo{{/if}}bar`) non
  viene ri-ancorato dai marcatori di riga: un marcatore `//` può occupare solo una riga intera, e
  inserirlo lì spezzerebbe una riga che il template non spezzava.
- Un blocco di codice indentato a 4 spazi **senza** fence non viene riconosciuto come verbatim.
  Riconoscerlo richiederebbe la regola CommonMark «il codice indentato non interrompe un paragrafo»,
  e sbagliarla significherebbe non sostituire un placeholder legittimo dentro prosa indentata —
  un falso positivo silenzioso, più frequente e peggiore del caso aperto.
- La chiave `this` di una riga adombra il wrapper del ciclo.
- Un commento `// pigrocrm:line=` scritto dall'autore del template collide col marcatore iniettato.
