# ADR-013: I vocabolari chiusi vivono in `core`, i registry si validano contro di loro

**Status:** Proposta — si ratifica con la PR di `docs/schema.md` (P0.3+S0.2)

**Contesto.** Il DSL (S0.5, sprint 1) ha bisogno di `EventType` e `MetricName` subito. technical-design §5.2 li voleva generati dai registry dei detector e delle metriche, che però arrivano con P2.4 e D10, in M2 e M3. Nel frattempo `tools/synth`, il DSL, la migrazione (`CHECK` su `events.type`) e il golden set dovrebbero usare un vocabolario che non esiste ancora.

**Decisione.** `EventType` e `MetricName` sono `StrEnum` in `packages/core/src/core/models/enums.py` fin da M0. Sono l'unica definizione:

- il DSL ne ricava i propri `Literal`;
- la migrazione ne ricava i `CHECK`;
- `tools/synth` produce ogni valore almeno una volta.

Quando arriva il registry (P2.4), **è lui a validarsi contro l'enum**, non il contrario:

- all'import, un detector registrato con un tipo che non è in `EventType` solleva un errore;
- `tests/test_graphs.py` verifica che `set(DETECTORS) == set(EventType)`, con un allowlist esplicito dei tipi ancora senza detector. L'allowlist deve essere vuoto entro la fine di M2.

La stessa regola vale per `MetricName` e il registry delle metriche (D10, M3).

**Conseguenze.**

- Aggiungere un tipo di evento richiede due passi: enum, migrazione e `schema.md` in una PR con due reviewer, e poi il detector. È voluto: `EventType` fa parte del contratto (CLAUDE.md), e un detector non deve poterlo allargare da solo.
- Viene meno la promessa «aggiungi un detector e l'assistente lo sa senza toccare nient'altro» (technical-design §5.2): adesso bisogna toccare anche l'enum. In cambio l'assistente, il sintetico e il database concordano sul vocabolario fin dal primo giorno.
- Un tipo nell'enum senza un detector che lo produce resta un rischio su dati reali: vedi `schema.md` §9, O1. Per questo goal, parata, punizione, cartellino e sostituzione **non** entrano nell'enum finché non esiste un produttore.
