# Desk Amber — R1-R5 : rapport d'extraction et de vérification

Livrable intermédiaire du chantier de remplacement du système « Nocturne » par « Desk Amber » (direction `1c` de `PATRICK__Directions_visuelles_export.html`). **Aucun fichier de production modifié à ce stade** — extraction, mapping et vérification de contraste uniquement. Implémentation (R6, gabarits, captures) en attente de validation.

Source : section `id="1c"` de l'export, décodée le 2026-08-11.

---

## R1 — Extraction exacte

**Espace colorimétrique** : 100 % OKLCH, aucun hex dans l'extrait (hors `rgba(...)` pour les ombres portées, comme sous Nocturne).

**Teinte de base** = hue `60` (neutres/fonds/bordures/texte), **accent** = hue `95`, chroma constant `0.15`.

| Rôle | Valeur OKLCH exacte | Usage observé |
|---|---|---|
| Fond boîtier (outer shell, dégradé) | `oklch(0.165 0.013 60)` → `oklch(0.14 0.011 60)` | fond du panneau principal |
| Fond carte/en-tête (dégradé) | `oklch(0.205 0.016 60)` → `oklch(0.185 0.015 60)` | header, cartes réglage ON |
| Fond carte OFF (plat) | `oklch(0.185 0.014 60)` | cartes désactivées, `opacity:.7` |
| Fond panneau élevé (CTA, dégradé diagonal) | `oklch(0.26 0.02 60)` → `oklch(0.21 0.017 60)` | résumé config + bouton lancer |
| Fond en-tête de table | `oklch(0.18 0.014 60)` | thead |
| Fond ligne survolée | `oklch(0.2 0.016 60)` | tr:hover |
| Fond input/select | `oklch(0.24 0.019 60)` | filtres |
| Fond chip/tag | `oklch(0.25 0.02 60)` → hover `oklch(0.28 0.022 60)` | tickers, modèles |
| Fond badge OFF | `oklch(0.23 0.018 60)` | pastille OFF |
| Texte bright | `oklch(0.94 0.01 60)` | titres carte, valeurs, IDs |
| Texte secondary | `oklch(0.7 0.015 60)` | nav, corps de table, inputs |
| Texte muted | `oklch(0.5 0.015 60)` | libellés OFF, dates, en-têtes table |
| Ink (texte sur accent plein) | `oklch(0.14 0.012 60)` | texte badge ON, texte bouton CTA |
| Accent | `oklch(0.78 0.15 95)` — hover `oklch(0.83 0.15 95)` | onglet actif, badges ON, sparkline, CTA |
| Bordure carte | `oklch(0.36 0.026 60 / 0.55)` — OFF : `oklch(0.34 0.024 60 / 0.4)` | |

**Typographie** : `'Space Grotesk'` (interface/titres/nav/boutons) + `'JetBrains Mono'` (IDs, tickers, dates, toutes colonnes numériques) — confirmé exactement comme attendu, à télécharger et auto-héberger.

**Ombres triple couche** (cartes de réglage) :
`inset 0 1px 0 rgba(255,255,255,.05), 0 2px 5px rgba(0,0,0,.4), 0 8px 16px -6px rgba(0,0,0,.45)` → hover : `inset …06, 0 3px 7px …5, 0 12px 22px -6px …55` + `translateY(-1px)`.

Le panneau boîtier (niveau le plus élevé) a une **4ᵉ couche** supplémentaire (`0 24px 48px -12px rgba(0,0,0,.7)`) — cohérent avec l'échelle à 4 niveaux déjà en place pour Nocturne.

**Rayons** : `2px` (badges, chips, pastille indice) / `3px` (cartes, header, boutons, inputs) / `4px` (panneau élevé CTA) — confirmé « 2–4px ».

> ⚠️ **Correction vs consigne initiale** : les badges ON/OFF ne sont **pas en pilule** dans cet extrait — `border-radius:2px`, un rectangle quasi carré, pas un radius ≈ moitié-hauteur. La pilule (20px) croisée en cherchant le fichier appartient à une **autre** section (hue 265), pas à `1c`. Documenté ici tel quel (2px) — à confirmer si une pilule est voulue malgré tout.

**Survol** : `translateY(-1px)` + halo accent uniquement sur le CTA et l'onglet actif (glow `0 0 22px oklch(0.78 0.15 95 / .45)`) — jamais sur un élément neutre ou de statut. Conforme à la doctrine déjà en place (« l'accent signale l'actif/interactif, jamais un jugement »).

---

## R2 — Mapping sémantique proposé

| Jeton existant | Nouvelle valeur (Amber) | Statut |
|---|---|---|
| `--ink` | `oklch(0.11 0.009 60)` | **dérivé** — absent de l'extrait (qui ne montre que le panneau boîté, pas le fond de page derrière) ; plus sombre que `--ground`, même famille |
| `--ground` | `oklch(0.165 0.013 60)` | extrait (stop clair du dégradé boîtier) |
| `--surface` | `oklch(0.205 0.016 60)` | extrait |
| `--raise` | `oklch(0.2 0.016 60)` | extrait (fond ligne survolée) |
| `--rule` / `--rule-strong` | `oklch(0.34 0.024 60 / 0.4)` / `oklch(0.36 0.026 60 / 0.55)` | extrait |
| `--text` | `oklch(0.94 0.01 60)` | extrait |
| `--text-2` | `oklch(0.7 0.015 60)` | extrait |
| `--text-3` | `oklch(0.62 0.015 60)` | **corrigé** — l'extrait utilise 0.5, échoue AA (R4) |
| `--accent` / `--accent-hover` | `oklch(0.78 0.15 95)` / `oklch(0.83 0.15 95)` | extrait |
| `--on-accent` | `oklch(0.14 0.012 60)` (= nouvel `--ink`) | extrait |

Aucun renommage littéral — seules les valeurs changent, comme pour Nocturne. Les composants partagés (`metric()`, `data_table()`, `status_badge()`, `empty_state()`, `error_state()`) ne sont pas touchés à ce stade.

---

## R3 — Couleurs de statut

**Correction vs prémisse initiale** : l'extrait contient en fait des valeurs pour 3 des 4 statuts (dans le script de données mock, pas dans une palette déclarée) — `done`/`running`/`failed`, en fond teinté 16 % + texte coloré :

- succès : `oklch(0.72 0.15 142)`
- « en cours » (mappé à info, pas vraiment « attention ») : `oklch(0.75 0.14 230)`
- erreur : `oklch(0.7 0.19 25)`
- **rien pour « en attente »** (aucun statut queued dans le mock).

**Problème réel trouvé (voir R4)** : le motif fond-teinté-16 %+texte-coloré **ne peut pas atteindre AA 4,5:1**, pas seulement pour les valeurs actuelles mais **structurellement** pour rouge/bleu à cette chroma — `oklch(…, 0.19, 25)` sort du gamut sRGB dès L≈0.72 et le contraste plafonne à 3,45:1 quelle que soit la luminosité poussée au-delà (vérifié par balayage empirique de L, pas supposé). Ce n'est pas un problème de valeur, c'est le motif visuel lui-même qui est intenable en AA pour ces teintes.

**Palette proposée** — bascule du motif « fond teinté + texte coloré » (non conforme) vers le motif déjà présent et déjà vérifié dans l'extrait pour ON/OFF (fond plein + texte `--ink` foncé) :

| Statut | Valeur | Origine |
|---|---|---|
| success | `oklch(0.72 0.15 142)` | extrait, inchangé |
| info | `oklch(0.75 0.14 230)` | extrait, inchangé |
| error | `oklch(0.70 0.19 25)` | extrait, inchangé |
| **attention** (absent de l'extrait) | ~~`oklch(0.75 0.16 80)`~~ → `oklch(0.75 0.16 67)` | **dérivé, révisé après implémentation (R6)** — hue 80 initiale trop proche de l'accent (95, écart 15°) pour rester nette sur les daltonismes protan/deutéranopes ; décalée à hue 67 (écart 28°). Contraste recalculé sur la nouvelle valeur, motif fond-plein + `--on-accent` : 8,89:1 (amélioré vs 8,80:1 avant) |
| **pending/attente** (absent de l'extrait) | `oklch(0.70 0.03 280)` | **dérivé** — faible chroma, hors famille accent, même doctrine que `--pending` sous Nocturne (sorti de la teinte active pour ne jamais se confondre avec l'interactif) |

> ⚠️ « Même teinte de base 60 » (consigne initiale) n'a **pas** été lue au sens littéral (hue=60 pour tous les statuts) — ça rendrait succès/attention/erreur indiscernables entre eux et du neutre. Lu comme « même méthode de construction (L/C cohérents avec le reste) », comme le fait l'extrait lui-même (hues distincts 142/230/25). **À confirmer** si ce n'est pas la lecture voulue.

---

## R4 — Contraste WCAG AA

Recalculé indépendamment (formules OKLab officielles → luminance relative → ratio WCAG), pas supposé conforme parce que l'extrait a l'air lisible.

| Paire | Ratio | AA texte normal (4,5:1) |
|---|---|---|
| `--text` sur `--surface` / `--ground` | 15,03 / 15,63 | ✅ |
| `--text-2` sur `--surface` / `--ground` | 6,70 / 7,20 | ✅ |
| `--text-3` **original (0.5)** sur `--surface`/`--ground`/badge OFF | 2,98 / 3,20 / **2,81** | ❌ |
| `--text-3` **corrigé (0.62)** sur `--surface`/`--ground`/badge OFF | 4,91 / 5,28 / 4,64 | ✅ |
| `--on-accent` sur `--accent` / `--accent-hover` | 9,97 / 11,83 | ✅ |
| `--accent` sur `--ground` / header | 9,65 / 8,98 | ✅ |
| status texte coloré sur fond teinté 16 % (motif original) | success 3,81 / info 3,93 / error **3,45 (plafond gamut, non atteignable)** | ❌ les trois |
| status `--on-accent` sur fond plein (motif corrigé) | success 8,48 / info 9,21 / error 6,85 / attention 8,80 / pending 7,42 | ✅ tous |
| status couleur (texte/dot) sur `--surface` opaque | 7,64 / 8,30 / 6,17 / 7,93 / 6,69 | ✅ tous |

---

## R5 — Mapping pages

Identique à Nocturne (aucune nouvelle réflexion de structure) : dashboard dense sur `/` (Poste de lancement, seul gabarit fourni par l'export), `JetBrains Mono` sur toutes les colonnes numériques des tables (`/runs`, `/universe`), pages de détail plus aérées via `--s*`/`--t-*` inchangés.

---

## Points à trancher avant R6

1. Badges ON/OFF en 2px carré (mesuré dans l'extrait) ou pilule forcée (absente de l'extrait, vue ailleurs dans le fichier) ?
2. Lecture de « même teinte de base 60 » pour les statuts dérivés (attention/pending) — confirmée ou pas ?

Aucun fichier de production touché par ce rapport.
