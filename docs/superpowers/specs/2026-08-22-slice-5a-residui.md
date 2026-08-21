# Slice 5A — residui noti

**Data:** 2026-08-22
**Stato:** 5A completo (landing, privacy, termini, build separata, routing sotto `/app/`)
**Scopo:** ciò che sappiamo essere aperto. Ogni voce è stata riprodotta eseguendo.

---

## D1 — Ricostruire l'immagine può non raccogliere una modifica a `spa.conf`

**Riprodotto durante la verifica di A7.** Aggiunta una direttiva a `deploy/nginx/spa.conf`, eseguito
`docker compose up -d --build web`: il comando ha riportato **successo** e il comportamento era
invariato. Interrogando il container, la riga appena scritta **non era nel file**: il layer del
`COPY deploy/nginx/spa.conf` era stato riusato dalla cache. Solo `docker compose build --no-cache web`
l'ha raccolta.

La conseguenza sul deploy vero è concreta: la pipeline fa `docker compose up -d --build` su SSH, e un
rilascio che cambia **soltanto** il routing di nginx può partire, dichiararsi riuscito, e continuare a
servire la configurazione precedente. Nessun test lo prenderebbe, perché tutti i test girano contro
codice, non contro l'immagine costruita.

**Cura possibile:** far verificare alla pipeline, dopo il deploy, una proprietà osservabile della
configurazione appena rilasciata — per esempio che `/login` risponda con una `Location` relativa —
invece di fidarsi dell'esito del build. Un `--no-cache` incondizionato costerebbe minuti a ogni
rilascio e curerebbe il sintomo, non la classe.

---

## D2 — La verifica in browser della landing non è stata fatta

`/`, `/privacy`, `/termini`, `/app/` e `/app/login` rispondono 200 dall'immagine costruita, i due
redirect sono relativi, i contenuti sono distinti e gli asset dell'app sono sotto `/app/assets/`.
Tutto questo è stato misurato con `curl`.

**Non** è stato verificato in un browser vero: la resa della grana e del rilievo, il funzionamento
del reveal allo scroll, e il rispetto di `prefers-reduced-motion`. Sono cose che solo un rendering
reale mostra, e la spec le tratta come parte del prodotto, non come decorazione.

---

## D3 — Il vecchio percorso `/login` sopravvive solo dietro nginx

`location = /login { return 302 /app/login; }` tiene in vita i link vecchi **in produzione**. Il dev
server di Vite non ha quella regola: in sviluppo `/login` è semplicemente un 404. Voluto — non vale
duplicare una regola di deploy nella configurazione di sviluppo — ma va saputo, perché un link
incollato da un collega si comporta in modo diverso nei due ambienti.
