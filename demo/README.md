# Demo Data

Everything in this folder is **synthetic demonstration data**, clearly
separated from the application's runtime database (`data/conai.db`, which
starts empty on every fresh checkout — see `data/.gitkeep`).

- `sample_rfp.txt` — a fabricated RFP excerpt for exercising the Document/RFP
  Intelligence Agent's requirement-extraction and mapping logic.

None of this data is loaded automatically. To try it, upload `sample_rfp.txt`
as a document when creating an engagement for any company name of your choice
(e.g. "Example Industrial Technologies Ltd").
