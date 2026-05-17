"""Tests unitaires pour les fonctions pures de matching."""
from __future__ import annotations

import pytest

from app.services.matching import (
    Candidate,
    _candidate_from_dict,
    _candidate_to_dict,
    band,
    normalize_name,
    score_candidate,
    tokenize,
)


pytestmark = pytest.mark.unit


class TestNormalize:
    def test_strip_and_upper(self):
        assert normalize_name("  Jean Dupont  ") == "JEAN DUPONT"

    def test_strip_accents(self):
        assert normalize_name("José Müller") == "JOSE MULLER"

    def test_strip_punctuation(self):
        assert normalize_name("O'Brien-Smith") == "O BRIEN SMITH"

    def test_collapse_whitespace(self):
        assert normalize_name("A   B\t\nC") == "A B C"

    def test_empty(self):
        assert normalize_name("") == ""
        assert normalize_name(None) == ""  # type: ignore[arg-type]


class TestTokenize:
    def test_basic(self):
        assert tokenize("JEAN DUPONT MARTIN") == ["JEAN", "DUPONT", "MARTIN"]

    def test_drop_short_tokens(self):
        # "A" est <2 chars → drop
        assert tokenize("JEAN A B C MARTIN") == ["JEAN", "MARTIN"]

    def test_empty(self):
        assert tokenize("") == []


class TestScoreAndBand:
    def test_score_max(self):
        assert score_candidate(1.0, 1.0) == 100

    def test_score_min(self):
        assert score_candidate(0.0, 0.0) == 0

    def test_score_weights_70_30(self):
        # 70% trigram + 30% token
        # 0.5 trigram, 0.0 token → 35
        assert score_candidate(0.5, 0.0) == 35
        # 0.0 trigram, 0.5 token → 15
        assert score_candidate(0.0, 0.5) == 15

    def test_score_clamped(self):
        assert score_candidate(2.0, 2.0) == 100   # over-clamped
        assert score_candidate(-1.0, -1.0) == 0   # under-clamped

    def test_band_thresholds(self):
        assert band(100) == "STRONG"
        assert band(85) == "STRONG"
        assert band(84) == "POSSIBLE"
        assert band(65) == "POSSIBLE"
        assert band(64) == "WEAK"
        assert band(0) == "WEAK"


class TestCandidateRoundtrip:
    def test_roundtrip_preserves_all_fields(self):
        original = Candidate(
            entity_id="abc-123",
            entity_risk="HIGH",
            primary_name="JOHN DOE",
            best_name_id=42,
            best_norm="JOHN DOE",
            trigram_sim=0.87,
            token_overlap=1.0,
            score=91,
            source_record_id="src-1",
            source_id=2,
        )
        roundtrip = _candidate_from_dict(_candidate_to_dict(original))
        assert roundtrip == original

    def test_roundtrip_handles_none_source(self):
        c = Candidate(
            entity_id="x", entity_risk="LOW", primary_name="X",
            best_name_id=1, best_norm="X", trigram_sim=0.1,
            token_overlap=0.0, score=7,
        )
        assert _candidate_from_dict(_candidate_to_dict(c)) == c
