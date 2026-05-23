from services.translation.core.terms.glossary import GlossaryEntry
from services.translation.core.terms.glossary import build_glossary_guidance
from services.translation.core.terms.glossary import context_matches
from services.translation.core.terms.glossary import glossary_hard_entries
from services.translation.core.terms.glossary import matched_glossary_entries
from services.translation.core.terms.glossary import normalize_glossary_entries
from services.translation.core.terms.glossary import parse_glossary_json
from services.translation.core.terms.glossary import term_pattern

__all__ = [
    "GlossaryEntry",
    "build_glossary_guidance",
    "context_matches",
    "glossary_hard_entries",
    "matched_glossary_entries",
    "normalize_glossary_entries",
    "parse_glossary_json",
    "term_pattern",
]
