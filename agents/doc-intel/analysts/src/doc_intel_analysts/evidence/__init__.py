"""Evidence store: doc-intel's third retrieval leg (LiteParse + LanceDB).

Page-keyed multimodal evidence over the corpus — page text, JPEG page
screenshots, extracted figures — with text embeddings via the AI Gateway and
image embeddings via local OpenCLIP. Interpretation happens at read time in
the agent loop; the knowledge graph (graph/) interprets once at ingest. The
two legs are independent: this package never touches `.cognee/`.
"""
