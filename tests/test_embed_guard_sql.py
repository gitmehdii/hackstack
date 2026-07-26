"""Tests de la garde optimiste d'écriture des embeddings (sans DB).

Enjeu : entre le SELECT (gardé en mémoire pendant des heures) et l'UPDATE, une promotion
peut avoir changé le texte d'un projet. Sans garde, on écrirait un vecteur calculé sur le
texte périmé du snapshot, et rien ne le rattraperait — le défaut même que corrige
`pipeline/load/promote.py`.

Ces tests existent surtout comme **filet de fusion**. La boucle d'encodage a été le siège
d'un conflit git entre le tri par longueur et cette garde : une résolution qui réduit les
lignes à `(texte, id)` supprime la garde sans casser aucun test de comportement. Ici, elle
casse.
"""

from __future__ import annotations

from pipeline.embed.embed import _UPDATE_SQL, EMBEDDED_TEXT_COLS, _text_for


def test_la_garde_compare_chaque_colonne_du_texte_encode() -> None:
    for col in EMBEDDED_TEXT_COLS:
        assert f"{col} IS NOT DISTINCT FROM %s" in _UPDATE_SQL, (
            f"la garde ne compare pas {col} : un changement de cette colonne pendant "
            "l'encodage laisserait écrire un vecteur périmé"
        )


def test_la_garde_utilise_is_not_distinct_from_et_pas_egal() -> None:
    # Sur une colonne NULL (cas majoritaire côté devpost, sans `description`), `=` renvoie
    # NULL et non `true` : l'UPDATE n'écrirait jamais rien. La garde bloquerait tout au lieu
    # de filtrer. `id = %s` reste légitime, la clé n'est jamais NULL.
    assert "IS NOT DISTINCT FROM" in _UPDATE_SQL
    for col in EMBEDDED_TEXT_COLS:
        assert f"{col} = %s" not in _UPDATE_SQL


def test_arite_des_parametres() -> None:
    # Propriété porteuse : vecteur + id + une comparaison par colonne de texte. Si une
    # fusion supprime le passage du texte en paramètre, l'arité ne colle plus et psycopg
    # échoue bruyamment au lieu d'écrire des vecteurs faux en silence.
    assert _UPDATE_SQL.count("%s") == 2 + len(EMBEDDED_TEXT_COLS)


def test_la_garde_filtre_sur_id() -> None:
    assert "WHERE id = %s" in _UPDATE_SQL


def test_text_for_suit_l_ordre_de_la_constante() -> None:
    # Variadique : le texte encodé suit EMBEDDED_TEXT_COLS sans correspondance positionnelle
    # à maintenir à la main. Un réordonnancement de la constante reste cohérent.
    assert _text_for("titre", "court", "long") == "titre\n\ncourt\n\nlong"
    assert _text_for("titre", None, "long") == "titre\n\nlong"
    assert _text_for("titre", "", None) == "titre"
    assert _text_for(*[None] * len(EMBEDDED_TEXT_COLS)) == ""
