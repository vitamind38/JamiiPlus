# Barrier taxonomy (draft for the phase 0 workshop)

The eight service barriers from the concept note, plus "other". This is the list loaded by
`jamii seed-themes`; after that it lives in the `theme` table and is changed under
Admin → Themes, not in code. Keywords feed the keyword baseline classifier only.

| Code | English | Kiswahili | Covers | Example report |
|---|---|---|---|---|
| `stockout` | Medicines & supplies | Dawa na vifaa | Facility stockouts, empty CHP kits, missing test kits | "mRDT kits zimeisha" |
| `transport` | Distance & transport | Umbali na usafiri | Distance, fares, roads, rivers, no ambulance | "Nauli ya boda ni 300 bob" |
| `cost` | Cost of care | Gharama ya matibabu | Charges for free services, unaffordable care, insurance gaps | "Wanaambiwa walipe Ksh 500 kwa kadi" |
| `staffing` | Staff shortage | Uhaba wa wahudumu | Closed or understaffed facilities, long queues, strikes | "Dispensary imefungwa Jumamosi" |
| `referral` | Referral feedback | Rufaa na majibu | Referrals not completed or never reported back | "Sijapata majibu ya rufaa tatu" |
| `training` | Training & supervision | Mafunzo na usimamizi | Missing training, refreshers, supportive supervision | "Hatujapata refresher mwaka huu" |
| `workload` | Workload & stipend | Mzigo wa kazi na posho | Late stipends, too many households, missing tools | "Posho ya miezi mitatu haijalipwa" |
| `social` | Cultural & social | Mila na jamii | Beliefs, stigma, misinformation, family decisions | "Wanakataa chanjo kwa uvumi" |
| `other` | Other | Mengineyo | Anything else; reviewed monthly for new themes | |

## Rules

- A theme is added by people after reviewing a cluster of "other" reports, never by a model.
- Hiding a theme (Admin → Themes → Hide) keeps old reports' labels; new reports cannot use it.
- Renaming a theme's label is safe at any time. Changing what a theme *means* splits the
  labelled data: add a new theme instead and hide the old one.
- USSD screens fit about six labels; labels should stay under 25 characters.

## Questions for the workshop

1. Should "weak upward communication" and "policy–practice gap" be themes, or are they what
   the whole system measures? (The draft treats them as the latter.)
2. Does the county want stockouts split by item type (medicines, test kits, CHP kit)?
3. Which local language, and who checks the Kiswahili wording with CHPs?
