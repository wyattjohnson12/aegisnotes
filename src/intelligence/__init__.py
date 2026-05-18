"""Deterministic, dependency-free intelligence layer (Phase 3).

Public surface:

* :class:`TfIdfIndex`           — corpus build + per-note vectors.
* :class:`TagExtractor`         — top-k TF-IDF terms with rule filters.
* :class:`StructuralParser`     — heading/bullet → topic tree.
* :class:`Summarizer`           — extractive summary by sentence scoring.
* :class:`SimilarityLinker`     — pairwise cosine over note vectors.
* :class:`IntelligenceProcessor`— orchestrator invoked from the OCR pipeline.

Everything in this package is pure Python. No external models, no
network calls, no NLTK downloads. Designed for Pi 5 / Railway.
"""
from src.intelligence.linker import SimilarityLinker
from src.intelligence.structural_parser import StructuralParser, TopicNode
from src.intelligence.summarizer import Summarizer
from src.intelligence.tag_extractor import TagExtractor, ScoredTag
from src.intelligence.tfidf import TfIdfIndex

# NB: ``IntelligenceProcessor`` and ``IntelligenceOutcome`` are intentionally
# NOT re-exported here. They import from ``src.database.repositories``, which
# in turn imports ``TopicNode`` from this package. Routing the processor
# through the package init would create a circular import. Callers should
# import the processor directly:
#
#     from src.intelligence.processor import IntelligenceProcessor

__all__ = [
    "ScoredTag",
    "SimilarityLinker",
    "StructuralParser",
    "Summarizer",
    "TagExtractor",
    "TfIdfIndex",
    "TopicNode",
]
