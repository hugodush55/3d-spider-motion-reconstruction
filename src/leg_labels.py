"""
leg_labels.py — ancrage anatomique et étiquetage des pointes détectées.

`leg_tips.py` rend un ensemble NON ORDONNÉ de pointes. Ce module dit laquelle
est L1. Validé en session 2026-09-25 (ETAT_ET_DECISIONS.md §24).

CE QUI A ÉCHOUÉ, ET POURQUOI C'EST INSTRUCTIF

Trois ancrages ont été essayés avant celui-ci, chacun réfuté par la mesure :

  * AXE DE TRAJECTOIRE (celui du fit actuel) — n'est réellement ancré que sur
    les 14 % de frames où l'animal marche ; le reste est propagé par continuité.
    Agitation mesurée : 3,12 °/frame en médiane, 48,6 au p90.
  * AXE DE SYMÉTRIE des pointes — un éventail de huit pattes est symétrique
    longitudinalement ET transversalement. La recherche verrouille une fois sur
    deux sur la perpendiculaire (écart médian 40°, p75 82°), et ne donne de
    toute façon qu'une direction, jamais un sens.
  * AXE PRINCIPAL du corps (PCA) — tiré par les variations de largeur, donc ne
    passe ni par la pointe de l'abdomen ni par la bouche. 20 % de retournements
    à 180°.

Et surtout, l'APPARIEMENT sur azimuts canoniques est structurellement fragile :
les azimuts sont espacés de 32 à 37°, l'écart postural médian vaut 15°, donc une
patte qui dévie d'un demi-intervalle bascule sur l'étiquette voisine. Mesure :
26 % de sauts entre frames consécutives.

CE QUI MARCHE

Deux idées de l'utilisateur, combinées :

  1. ANCRER SUR L'ABDOMEN. C'est la seule structure qui donne un SENS et pas
     seulement une direction. On le trouve par le DIAMÈTRE GÉODÉSIQUE du corps :
     les deux points les plus éloignés l'un de l'autre en suivant le corps sont
     la pointe de l'abdomen et la bouche, par construction. Puis l'épaisseur
     locale désigne lequel est l'abdomen (rapport mesuré 1,49 en médiane,
     minimum 1,23 sur 90 frames).
     Stabilité : 0,27 °/frame en médiane, 0,69 au p90, ZÉRO retournement sur
     89 transitions — douze fois mieux que l'axe de trajectoire.

  2. COMPTER PLUTÔT QU'APPARIER. On ne compare aucune patte à une position
     attendue : on tourne autour du corps depuis l'abdomen et on nomme dans
     l'ordre rencontré. Un ordre ne change que si deux pattes se croisent
     vraiment ; une imprécision d'ancrage reste une imprécision d'ancrage au
     lieu de devenir une erreur d'identité.
     Mesure : 0 saut sur 712 transitions, contre 26 % pour l'appariement.

LA LOI DE CHIRALITÉ

Le côté (gauche/droite) tient à UNE hypothèse, vraie pour tout ce corpus :
la caméra est toujours AU-DESSUS de l'animal, qui marche sur le tissu. On ne
voit jamais sa face ventrale, donc la chiralité est constante et un seul signe
suffit pour toute une session de tournage.

Si un jour l'animal était filmé par en dessous (vitre, terrarium transparent),
ce signe s'inverserait — d'où `chirality` en paramètre explicite plutôt qu'en
constante enfouie.
"""

from typing import Dict, List, Optional, Sequence, Tuple

import cv2
import numpy as np

__all__ = ["body_extremities", "cyclic_order", "label_tips"]

_K3 = np.ones((3, 3), np.uint8)


def _geodesic(mask: np.ndarray, seed: np.ndarray, cap: int = 3000) -> np.ndarray:
    d = np.full(mask.shape, -1, np.int32)
    d[seed] = 0
    cur = seed.copy()
    for step in range(1, cap + 1):
        nxt = (cv2.dilate(cur.astype(np.uint8), _K3) > 0) & mask & (d < 0)
        if not nxt.any():
            break
        d[nxt] = step
        cur |= nxt
    return d


def _farthest(mask: np.ndarray, d: np.ndarray) -> np.ndarray:
    v = np.where(mask, d, -1)
    i = int(np.argmax(v))
    return np.array([i % mask.shape[1], i // mask.shape[1]], float)


def body_extremities(mask: np.ndarray, thick_frac: float = 0.22
                     ) -> Optional[Dict[str, object]]:
    """Pointe de l'abdomen et extrémité buccale, par diamètre géodésique du corps.

    Renvoie ``{"abdomen", "mouth", "u", "ratio", "body", "diam"}`` où ``u`` est
    le vecteur unitaire bouche → abdomen, ou None si le corps n'est pas isolable.

    `thick_frac` seuille la transformée de distance pour isoler le corps. À 0,40
    le contour ne gardait qu'UN lobe et l'étranglement était cherché à
    l'intérieur de l'abdomen ; 0,22 capture les deux masses (allongement mesuré
    2,41). Ne pas remonter sans revérifier visuellement que le contour épouse
    céphalothorax ET abdomen.
    """
    # Recadrage avant tout calcul : cette fonction fait DEUX propagations
    # géodésiques, chacune une série de dilatations sur l'image entière. Sur un
    # masque 4K c'est seize fois plus de pixels que nécessaire (voir
    # leg_tips.crop_to_mask, qui explique pourquoi l'opération reste exacte).
    # `abdomen` et `mouth` sont replacés en pixels image à la sortie ; `u`,
    # `diam` et `ratio` sont invariants par translation. `body` reste dans le
    # repère du recadrage — aucun appelant du dépôt ne le lit, et `org` est
    # rendu pour ceux qui voudraient le faire.
    from leg_tips import crop_to_mask
    m_c, dt, org = crop_to_mask(mask.astype(bool))
    if m_c is None:
        return None
    ox, oy = org
    m = m_c.astype(np.uint8)
    thick = float(dt.max())
    if thick <= 0:
        return None
    body = dt > thick_frac * thick
    n, lbl, st, _ = cv2.connectedComponentsWithStats(body.astype(np.uint8), 8)
    if n < 2:
        return None
    body = lbl == (1 + int(np.argmax(st[1:, 4])))
    if body.sum() < 60:
        return None

    ys, xs = np.nonzero(body)
    seed = np.zeros_like(body)
    seed[ys[0], xs[0]] = True
    A = _farthest(body, _geodesic(body, seed))
    sa = np.zeros_like(body)
    sa[int(A[1]), int(A[0])] = True
    B = _farthest(body, _geodesic(body, sa))

    u = B - A
    L = float(np.linalg.norm(u))
    if L < 2:
        return None
    u = u / L

    def local_thick(pt: np.ndarray) -> float:
        r = max(6, int(0.30 * L))
        yy, xx = np.ogrid[:body.shape[0], :body.shape[1]]
        sel = (((xx - pt[0]) ** 2 + (yy - pt[1]) ** 2) < r * r) & body
        return float(dt[sel].max()) if sel.any() else 0.0

    tA, tB = local_thick(A), local_thick(B)
    if tA > tB:                       # l'abdomen est l'extrémité la plus épaisse
        A, B, u, tA, tB = B, A, -u, tB, tA
    off = np.array([ox, oy], float)
    return dict(abdomen=B + off, mouth=A + off, u=u, diam=L, body=body,
                org=org, ratio=float(tB / max(tA, 1e-9)))


def cyclic_order(species) -> List[str]:
    """Ordre des appendices rencontrés en tournant depuis l'abdomen.

    Dérivé des azimuts canoniques déclarés par l'espèce, pas codé en dur : la
    punaise (6 pattes + 2 antennes) doit marcher sans modification. L'abdomen
    est à 180° de l'avant, d'où le tri par ``(180 - relèvement) mod 360``.
    """
    items = [(a.label, (180.0 - a.side * a.azimuth_deg) % 360.0)
             for a in species.appendages]
    items.sort(key=lambda t: t[1])
    return [lab for lab, _ in items]


def label_tips(tips_uv: Sequence[Sequence[float]],
               centre: Sequence[float],
               abdomen_uv: Sequence[float],
               order: Sequence[str],
               chirality: int = +1) -> Dict[str, np.ndarray]:
    """Nomme les pointes par ordre cyclique depuis l'abdomen.

    `chirality` : +1 ou -1 selon le sens de rotation. Constant pour un corpus
    filmé du même côté (voir l'en-tête du module). Vérifié à +1 sur
    daphne_1875, caméra au-dessus de l'animal.

    Renvoie moins d'étiquettes que `order` si moins de pointes sont fournies —
    et c'est le point de fragilité connu : une pointe manquante DÉCALE tout ce
    qui suit. L'appelant doit exiger le compte complet, ou repérer le trou
    angulaire avant de nommer.
    """
    tips = np.asarray(tips_uv, float)
    c = np.asarray(centre, float)
    ref = np.asarray(abdomen_uv, float) - c
    n = float(np.linalg.norm(ref))
    if n < 1e-6 or len(tips) == 0:
        return {}
    ref = ref / n
    perp = np.array([-ref[1], ref[0]]) * float(np.sign(chirality) or 1)
    v = tips - c
    ang = np.arctan2(v @ perp, v @ ref) % (2 * np.pi)      # 0 = vers l'abdomen
    idx = np.argsort(ang)
    return {order[k]: tips[i] for k, i in enumerate(idx[:len(order)])}
