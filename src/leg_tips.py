"""
leg_tips.py — détection directe des pointes d'appendices dans un masque.

Prototype validé en session 2026-09-25 (voir ETAT_ET_DECISIONS.md §23.7).

POURQUOI. Le fit actuel ajuste 25 paramètres pour que la projection du gabarit
recouvre la silhouette. C'est un problème d'alignement d'images, non convexe, et
surtout AVEUGLE À LA PROFONDEUR : une patte étirée vers la caméra se projette
courte, tombe dans le masque, et le coût est satisfait alors que la position 3D
est anatomiquement impossible (§23.4, allonge mesurée jusqu'à 4,46 rayons).

Détecter d'abord les pointes donne au fit des CIBLES EXPLICITES. Une patte ne
peut alors plus dériver dans l'axe de vue sans pénalité : le mode d'échec
disparaît par construction au lieu d'être plafonné par une borne.

MÉTHODE, sans dépendance exotique (cv2.ximgproc est absent de cet environnement) :

  1. le CORPS est le noyau du masque après érosion proportionnelle à son
     épaisseur maximale — le seul endroit épais d'une silhouette d'arthropode ;
  2. la DISTANCE GÉODÉSIQUE depuis ce corps est propagée À L'INTÉRIEUR du
     masque. Contrairement à une distance euclidienne, elle suit les appendices
     au lieu de couper à travers le fond ;
  3. les POINTES sont les maxima locaux de cette distance : un pixel dont aucun
     voisin n'est plus loin du corps est un bout de branche.

Deux filtres, tous deux réglés par la mesure :

  * ANGULAIRE — deux maxima dans la même direction appartiennent au même
    appendice (un coude en crée un second). Le seuil est critique : les vraies
    fusions se font à moins de 1,5°, deux pattes DISTINCTES peuvent n'être
    séparées que de 19,7°. À 22° on perdait une patte sur trois frames ; à 8°
    les pattes manquées tombent de 23/40 à 11/40.
  * LONGUEUR — un vrai bout de patte est loin du corps. Les faux positifs
    (aspérités du masque, bases d'appendices) sont proches.

CE QUE ÇA NE FAIT PAS. Les pointes ne sont pas IDENTIFIÉES : on obtient un
nuage non ordonné, pas « L1, L2… ». L'appariement à des étiquettes anatomiques
reste à faire, et c'est là que la continuité temporelle et la profondeur
(§23.6 — DepthPro résout bien les pattes une par une) auront leur rôle.

ATTENTION. Compter huit pointes ne prouve RIEN : sans regroupement angulaire on
en trouve toujours huit, dont deux sur la même patte et une manquée. Utiliser
`angular_gap()` comme contrôle — il est indépendant du compte.
"""

from typing import List, Optional, Tuple

import cv2
import numpy as np

__all__ = ["find_tips", "angular_gap", "geodesic_from_body"]


def crop_to_mask(mask: np.ndarray, pad0: int = 64
                 ) -> Tuple[Optional[np.ndarray], Optional[np.ndarray], Tuple[int, int]]:
    """Recadre le masque sur sa boîte englobante, avec une marge de zéros.

    Renvoie ``(masque_recadré, distance_transform, (x0, y0))``. Les coordonnées
    rendues par les fonctions de ce module sont replacées en pixels image en
    ajoutant ``(x0, y0)`` — c'est à l'appelant de ne pas l'oublier, et les deux
    fonctions publiques d'ici le font déjà.

    POURQUOI. La propagation géodésique itère des dilatations sur TOUT le
    masque : 3840 × 2160 = 8,3 Mpx, alors que l'animal en occupe environ 0,5.
    Chaque itération balayait donc seize fois trop de pixels, et il y en a des
    centaines. Mesuré : 4,65 s par frame, contre 42 min pour tout le reste du
    pipeline réuni sur une prise de 2000 frames.

    POURQUOI C'EST EXACT, ET PAS UNE APPROXIMATION. Hors de la boîte
    englobante le masque vaut zéro par définition ; entourer le recadrage de
    zéros reproduit donc littéralement le voisinage d'origine. Il suffit que la
    marge dépasse la portée des opérations qui lisent les voisins :

      * `distanceTransform` cherche le fond le plus proche — portée = épaisseur
        maximale du masque ;
      * l'érosion du corps a un rayon 0,55 × cette épaisseur ;
      * les dilatations géodésiques restent à l'intérieur du masque.

    D'où la vérification explicite ci-dessous : si la marge n'excède pas
    l'épaisseur mesurée, on recadre une seconde fois avec la bonne marge. Sans
    ce contrôle le recadrage serait *presque* exact — et un « presque » sur une
    transformée de distance déplace les pointes sans rien signaler.
    """
    ys, xs = np.nonzero(mask)
    if len(xs) == 0:
        return None, None, (0, 0)
    H, W = mask.shape
    m8 = mask.astype(np.uint8)
    for pad in (pad0, None):
        if pad is None:                       # seconde passe, marge ajustée
            pad = int(thick) + 8
        x0, y0 = max(0, int(xs.min()) - pad), max(0, int(ys.min()) - pad)
        x1, y1 = min(W, int(xs.max()) + 1 + pad), min(H, int(ys.max()) + 1 + pad)
        crop = np.ascontiguousarray(m8[y0:y1, x0:x1])
        dt = cv2.distanceTransform(crop, cv2.DIST_L2, 5)
        thick = float(dt.max())
        if thick + 4 <= pad or (x1 - x0, y1 - y0) == (W, H):
            return crop > 0, dt, (x0, y0)
    return crop > 0, dt, (x0, y0)


def geodesic_from_body(mask: np.ndarray, body: np.ndarray, cap: int = 4000) -> np.ndarray:
    """Distance géodésique (en pas de dilatation) depuis `body`, restreinte à `mask`.

    Renvoie -1 hors du masque et sur les pixels non atteints.
    """
    dist = np.full(mask.shape, -1, np.int32)
    dist[body] = 0
    cur = body.copy()
    k = np.ones((3, 3), np.uint8)
    for step in range(1, cap + 1):
        nxt = (cv2.dilate(cur.astype(np.uint8), k) > 0) & mask & (dist < 0)
        if not nxt.any():
            break
        dist[nxt] = step
        cur |= nxt
    return dist


def find_tips(
    mask: np.ndarray,
    n_max: int = 8,
    ang_tol_deg: float = 8.0,
    min_len_frac: float = 0.30,
    min_branch: int = 12,
) -> Tuple[List[Tuple[float, float, float]], Optional[Tuple[float, float]]]:
    """Pointes d'appendices et centre du corps.

    Renvoie ``(tips, centre)`` où chaque pointe est ``(x, y, longueur_géodésique)``,
    triée par longueur décroissante. ``centre`` vaut None si le corps n'a pas pu
    être isolé (masque trop fin ou dégénéré).

    `ang_tol_deg` par défaut à 8 : mesuré, voir le module. Ne pas remonter à 22
    sans refaire la mesure — c'était la valeur qui perdait une patte.
    """
    mask = mask.astype(bool)
    if mask.sum() < 500:
        return [], None

    # tout ce qui suit travaille sur le recadrage ; `ox, oy` replace les
    # coordonnées rendues en pixels image (voir crop_to_mask).
    mask, dt, (ox, oy) = crop_to_mask(mask)
    if mask is None:
        return [], None
    thick = float(dt.max())
    r = max(3, int(0.55 * thick))
    body = cv2.erode(mask.astype(np.uint8), np.ones((2 * r + 1,) * 2, np.uint8)) > 0
    if body.sum() < 20:                       # silhouette très fine : on relâche
        body = dt > 0.75 * thick
    if body.sum() < 20:
        return [], None

    by, bx = np.nonzero(body)
    cx, cy = float(bx.mean()), float(by.mean())

    d = geodesic_from_body(mask, body)
    dd = np.where(d < 0, -1, d).astype(np.float32)
    local_max = cv2.dilate(dd, np.ones((7, 7), np.uint8))
    peaks = (dd > min_branch) & (dd >= local_max - 0.5)
    if not peaks.any():
        return [], (cx + ox, cy + oy)

    n, lbl, _, _ = cv2.connectedComponentsWithStats(peaks.astype(np.uint8), 8)
    cand = []
    for i in range(1, n):
        sel = lbl == i
        ys, xs = np.nonzero(sel)
        j = int(np.argmax(dd[sel]))
        cand.append((float(xs[j]), float(ys[j]), float(dd[sel].max())))
    cand.sort(key=lambda t: -t[2])

    # regroupement angulaire : même direction depuis le corps = même appendice
    tol = np.deg2rad(ang_tol_deg)
    kept: List[Tuple[float, float, float]] = []
    for x, y, g in cand:
        a = np.arctan2(y - cy, x - cx)
        if all(abs(np.angle(np.exp(1j * (a - np.arctan2(v[1] - cy, v[0] - cx))))) > tol
               for v in kept):
            kept.append((x, y, g))

    if kept:
        kept = [t for t in kept if t[2] >= min_len_frac * kept[0][2]][:n_max]
    # retour en pixels image : les angles et longueurs ci-dessus sont invariants
    # par translation, seul le point final doit être replacé.
    kept = [(x + ox, y + oy, g) for x, y, g in kept]
    return kept, (cx + ox, cy + oy)


def angular_gap(tips, centre) -> float:
    """Plus grand secteur angulaire sans pointe, en degrés.

    Contrôle INDÉPENDANT du compte de pointes, et c'est tout son intérêt : huit
    pointes dont deux sur le même appendice laissent un trou béant, que le
    simple comptage ne voit pas. Chez une araignée saine la valeur reste
    au voisinage de 90° ; nettement au-delà, un appendice a été manqué.
    """
    if centre is None or len(tips) < 2:
        return 360.0
    a = sorted(np.degrees(np.arctan2(y - centre[1], x - centre[0])) % 360
               for x, y, _ in tips)
    return max((a[(i + 1) % len(a)] - a[i]) % 360 for i in range(len(a)))
