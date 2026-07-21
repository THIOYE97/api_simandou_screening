"""
Analyseurs des listes ONU, OFAC et UE.

Repris de l'agent autonome « sanctions_agent », dont la stratégie de mise à
jour — purge puis rechargement — était inapplicable : `screening_matches`
référence `entities` sans `ON DELETE`, si bien que la purge échouait dès
qu'une vérification avait rapproché une entité. Elle réattribuait de surcroît
de nouveaux identifiants à chaque exécution, ce qui aurait détaché les
dossiers déjà décidés de leurs correspondances.

Seuls les ANALYSEURS sont conservés : ils sont éprouvés sur les XML réels. Le
chargement passe désormais par le moteur d'ingestion du back-end, qui tient
`source_records` et sait radier sans supprimer.
"""
