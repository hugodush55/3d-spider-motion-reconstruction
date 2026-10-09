# Method

A curated account of how footfalls are measured from monocular video. It gives
the pipeline, the parameters that matter and the measurement behind each one.
It is not the full decision record: the catalogue of refuted hypotheses stays
private until publication.

---

## 1. The inversion

The obvious approach is to reconstruct the animal: fit a deformable template so
that its projection covers the silhouette. That was tried first and it fails for
a structural reason. Template fitting against a silhouette is an image-alignment
problem, and it is **blind along the viewing axis**: a leg stretched toward the
camera projects short, lands inside the mask, and satisfies the cost function
while sitting at an anatomically impossible 3D position. Measured reach reached
4.46 body radii before the failure was bounded.

The animal also deforms between viewpoints, so it cannot be triangulated or
fused across frames. Camera motion, which normally helps, gives nothing here.

The ground does not deform. So the pipeline reconstructs the **scene**, with the
animal masked out of feature matching, and camera motion becomes an asset again.
That gives, per take, a camera pose per frame and a ground plane. And it makes
one quantity exact rather than estimated:

> A foot that is planted lies on the ground plane. Its 3D position is therefore
> the intersection of its optical ray with that plane — a closed-form
> intersection, with no fitting and no depth ambiguity.

A foot in flight does not lie on the plane and is not determined. So the
pipeline's central question is not *where are the legs* but *which feet are
planted*. Identity and kinematics become secondary; contact becomes primary.

## 2. Scene reconstruction

Sparse photogrammetry (COLMAP), features masked inside the animal's silhouette
so that a deforming body cannot corrupt the rigid reconstruction. Dense
reconstruction was dropped — unreliable on this footage.

| Take | Images registered | Mean reprojection error |
|---|---|---|
| A (33 s) | 100/100 | 1.14 px |
| B (17 s) | 51/51 | 1.19 px |
| C (56 s) | 170/170 | 0.99 px |
| Second species | 43/43 | 0.74 px, 16 386 scene points |

Poses are interpolated to frames between keyframes by SLERP on rotation and
linear interpolation on translation.

**Metric scale** comes from an object of known dimension back-projected onto the
scene, giving 0.2983 mm/px on the take where it was run. The control that it is
not circular: scale recovered independently from separate frame subsets agrees
to a 6 % coefficient of variation — the subsets share the reconstruction but not
the measurement.

### The ground plane

One plane per take, fitted where the animal actually walked, by iteratively
reweighted least squares with Tukey weights. Residual 0.46 in animal radii.

Two things are worth recording because they are easy to get wrong.

**Weighting, not thresholding.** A threshold plus RANSAC selects a consensus set
and then fits it, which is self-confirming: the inliers are defined by the model
being tested. Weighting keeps every point and lets the loss decide how much each
one counts, so the fit can still be pulled by evidence it would rather ignore.

**Coefficient of variation is not a control here.** Two candidate planes 59°
apart both gave a CV of 0.22 on the same data. A statistic that cannot
distinguish planes at 59° cannot validate a plane. The usable control is the
correlation between plane-relative height and an independent quantity, not the
dispersion of the residuals.

The plane normal drifts 0.218 °/frame. Over seven frames — the duration of one
stance — the plane rotates 1.5°. Everything **local** therefore survives; global
claims across a whole take do not.

## 3. Segmentation

SAM2, prompted from sparse hand annotation and propagated through the take.
575 bounding boxes were annotated by hand across the corpus and spline-
interpolated to all frames to seed the propagation. Per-frame masks are flagged
as area outliers for review rather than silently accepted.

## 4. Appendage tips from mask geometry

No learned keypoint model, and no exotic dependency.

1. The **body** is the core of the mask after an erosion proportional to the
   mask's maximum thickness — the only thick region in an arthropod silhouette.
2. **Geodesic distance** from that body is propagated *inside* the mask. Unlike
   a Euclidean distance it follows the appendages instead of cutting across the
   background.
3. **Tips** are the local maxima of that field: a pixel no neighbour of which is
   further from the body is the end of a branch.

Two filters, both set by measurement rather than taste.

**Angular grouping at 8°.** Two maxima in the same direction from the body
belong to the same appendage — a bent joint creates a spurious second maximum.
The threshold is tight because the two error modes are close together: genuine
duplicate maxima on one leg sit within 1.5° of each other, while two genuinely
distinct legs can be only 19.7° apart. At 22° a real leg was lost in one frame
out of three; at 8°, missed legs fall from 23/40 to 11/40.

**Length filter.** A real leg end is far from the body along the mask; mask
roughness and appendage bases are close to it.

**The control that matters.** Counting eight tips proves nothing — without
angular grouping one finds eight almost always, two of them on the same leg and
one leg missed. The honest diagnostic is `angular_gap()`, the largest angular
sector containing no tip, which is **independent of the tip count** and
therefore cannot be satisfied by the failure it is meant to catch.

Cropping the mask to its bounding box before the geodesic propagation leaves the
result exact (the operation is translation-invariant) and makes it 14× faster:
4.65 s to 0.333 s per frame.

## 5. Identity, by counting rather than matching

Tip detection returns an unordered set. Naming it is a separate problem, and
matching tips to canonical azimuths fails structurally: the canonical azimuths
are 32–37° apart while the median postural deviation is 15°, so a leg deviating
by half an interval flips onto its neighbour's label. Measured: 26 % of
consecutive frames disagreed.

Two changes fix it.

**Anchor on the abdomen.** It is the only structure that gives a *sense* and not
merely a direction. It is found by the **geodesic diameter of the body**: the two
mutually furthest points along the body are, by construction, the abdomen tip
and the mouth. Local thickness then says which is which (measured ratio 1.49
median, 1.23 minimum over 90 frames). Stability: 0.27 °/frame median, zero
180° flips over 89 transitions — twelve times better than anchoring on the
trajectory axis.

**Count, don't match.** No tip is compared to an expected position. The method
walks around the body starting from the abdomen and names appendages in the
order encountered. An order changes only if two legs genuinely cross; an anchor
imprecision stays an anchor imprecision instead of becoming an identity error.
Measured: **0 jumps over 712 transitions.**

Chirality — which way round to walk — rests on one assumption true of this whole
corpus: the camera is always above the animal, so the ventral side is never
seen and the handedness is constant for a shooting session. It is an explicit
parameter rather than a buried constant, because filming through glass from
below would invert it.

Side is also recoverable from leg convexity, which alternates left and right.
Per frame that classifies only 77 % of legs, which is useless; as a majority
vote over eleven frames it reaches 99.6 %.

## 6. Contact determination

A planted foot is **fixed in the world**, not fixed relative to the body. The
statistic is, per tip and per frame,

```
s = max( distance to the nearest tip in frame i-1 ,
         distance to the nearest tip in frame i+1 )
```

in animal radii, computed on the plane. Small `s` means the foot did not move in
the world across either neighbouring frame.

Measured distribution of `s`:

| p10 | p25 | median | p75 | p90 |
|---|---|---|---|---|
| 0.007 | 0.011 | 0.021 | 0.063 | 0.152 |

At an operating point of 0.025: 54.6 % of tip-frames are contacts, 4.21 feet
down on average, 131 footfalls, 200 ms median stance.

**This threshold is chosen, not derived, and that must be stated plainly.** The
distribution is unimodal — there is no valley to cut at. The operating point was
picked by looking at where it placed the duty factor relative to what the
literature reports for octopod walking. That is a defensible engineering choice
and it is not a measurement. A derived threshold requires ground truth.

**The witness, and its weakness.** Against a control in which tip identities are
shuffled between frames, the criterion separates by a factor of 651. That shows
the criterion is not firing on noise. It does **not** show the threshold is in
the right place, and it is a weak control precisely because the alternative it
rejects is so implausible.

**One control was inverted and is worth recording as a warning.** "A contact is
immobile" is a statement in the *world* frame; "a tip moves with the body" is a
statement in the *body* frame. Having conflated them, a near-zero correlation
was read as a failure when it is exactly what should be expected, and a ratio of
1.01 presented as the strongest validation in fact said that the tips were
moving *with* the body — that is, that they were not planted at all. The correct
control compares contacts against the general population of tips.

## 7. What limits the method today

The dominant failure is **occlusion**, and it has now been separated from the
competing explanation.

Two legs close in image angle merge into a single branch of the mask and the tip
count drops. The alternative hypothesis was that the detector mislocates the tip
by climbing a folded leg. These have disjoint signatures — a merge lowers the
count, a climb keeps the count at eight while collapsing a geodesic length — so
they are separately measurable.

| | result |
|---|---|
| Frames with all 8 tips, clean segment | 89.3 % (267/299) |
| Frames with all 8 tips, full take | 80.0 % |
| Min angular separation before a count drop | median **9.4°** (n = 15) |
| Min angular separation when the count holds | median **14.3°** (n = 251) |
| Permuted witness, 20 000 draws | **p = 0.011** |
| Drops preceded by a separation under 10° | 53.3 %, against 16.3 % of holds |
| Geodesic length below 70 % of its own local median | **1.31 %** of observations |

So merging is confirmed as the mechanism and detector climbing is refuted at
1.31 %. Three caveats: n = 15 drop events is small; the effect is an enrichment
and not a separation, since 86.7 % of drops have a separation under 15° but so
do 53.8 % of holds, which makes angular closeness evidence of the mechanism
rather than a usable predictor; and the clean segment was selected for its
cleanliness, so 10.7 % incomplete frames is a best case.

**Episode durations**, over a full take: 68 episodes, median 4 frames (67 ms at
60 fps), p75 6, p90 16, maximum 28 (467 ms). Against a median stance of 200 ms,
roughly one episode in ten lasts longer than a whole stance. A foot can
therefore touch down, stay hidden for the entire duration of its contact, and
never be measured — and because legs cross at particular phases of the gait
cycle, those losses are not random with respect to the quantity being measured.

The consequences for the fix are specific. Short episodes — 63 % are four frames
or fewer — close **rigorously** rather than by interpolation: if a tip is present
before and after at positions identical to within the contact threshold, the
contact criterion itself establishes that the foot was planted throughout, and a
planted foot is stationary, so filling the gap is exact rather than approximate.
The long tail is different. The information needed to place a hidden tip is not
in the frame, and no monocular model can recover what a single view does not
contain: a learned prior can guess it, a second viewpoint measures it. Two legs
superposed from one camera are almost never superposed from another.

## 8. How claims are validated

Four rules, derived from having been wrong repeatedly.

**Every claim gets a witness that can fail.** A control which the hypothesis
satisfies by construction is not a control. Shuffled-identity and permuted-group
witnesses are used to establish what a null result looks like on the same data.

**Acceptance criteria are fixed before looking.** Each workstream has a numeric
gate written down in advance, and failing it stops the workstream rather than
starting a negotiation. This is the partial answer to not having applied a
multiple-comparison correction: it is a de facto pre-registration.

**Independent estimates are preferred to internal consistency.** A second
estimator that shares no assumption with the first is worth more than any
goodness-of-fit. This is why monocular depth is interesting: not for *placing* a
point, where it is useless, but for *separating* legs, where it was measured to
resolve them individually at ratios from 3.79 to 9.71.

**Refutations are recorded with their measurement.** Eight hypotheses were
rejected by witness or guard-rail, and five bugs were found in the project's own
diagnostic tools — including a smoothing routine that was never actually called
by the analysis scripts, and a percentile fallback that selected a fixed
fraction of frames *by construction*, found twice in two different scripts. A
pipeline that drifts slowly is more dangerous than one that jumps, because
smooth error passes every plausibility check: the ground plane was wrong for
weeks while rotating a credible 0.218° per frame.

## 9. Known gaps

- No independent ground truth, therefore no error bars
- Contact threshold chosen rather than derived
- Rolling shutter unquantified
- Ground is textile, approximated by one plane per take
- Metric scale run on only one species
- 20 % of frames incomplete, non-randomly with respect to gait phase
- No multiple-comparison correction
- Not yet packaged for reproducible re-execution
