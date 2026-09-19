# ADR-006: Divisione del lavoro tra le due aree

**Status:** Aperta — da decidere a voce

Vincoli: l'inferenza gira sulla macchina con la GPU, ma il worker è un servizio condiviso via coda, quindi chi lavora sull'assistente non ha bisogno della scheda. Il training è su Kaggle.
