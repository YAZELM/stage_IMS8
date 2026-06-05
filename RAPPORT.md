# Comparaison simple des simulateurs

## Objectif

Le but est de comparer VIVID aux simulateurs avec peu de metriques, mais de les lire correctement selon les conditions de scene.
VIVID est utilise comme reference et reste visible dans chaque figure.

Les metriques principales sont `events/s`, `events/pixel`, `ON ratio` et `pixels utilises`.
Deux controles temporels completent la lecture: le delai inter-event par pixel et les `events/s` par fenetre temporelle.

## Methode courte

- `events/s = n_events / duree`.
- `events/pixel = n_events / (largeur * hauteur)`.
- `ON ratio = n_ON / n_events`.
- `pixels utilises = pixels_actifs / pixels_totaux`.
- `delai_pixel = (t_dernier - t_premier) / (n_events_pixel - 1)` pour chaque pixel avec au moins deux evenements.

Le calcul du delai considere bien tous les pixels du capteur. Les pixels avec moins de deux evenements sont comptes, mais ils n'ont pas de delai inter-event defini.
Les resolutions utilisees sont `240x180` pour VIVID et `346x260` pour les simulateurs.

## Verification rapide

- Fichiers analyses: 60.
- Fichiers invalides: 0.
- Fichiers avec timestamps non ordonnes sur echantillon: 10.

Les timestamps non ordonnes concernent `pix2nvs`. Les metriques de comptage restent exploitables, mais toute analyse temporelle fine de `pix2nvs` doit rester prudente.

## Vue globale des resultats

| Source | events/s | events/pixel | ON ratio | pixels utilises | delai/pixel | pixels avec delai | events/s vs VIVID | events/pixel vs VIVID | delai vs VIVID | RMSE fenetres |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| vivid | 1.95e+05 | 109.7 | 42.4% | 99.9% | 6.47e+05 | 99.6% | 1.000 | 1.000 | 1.000 | 0.000 |
| dvs_voltmeter | 9.99e+05 | 262.5 | 53.7% | 100.0% | 9.55e+05 | 98.2% | 5.112 | 2.393 | 1.476 | 8.82e+05 |
| iebcs | 5.74e+05 | 159.5 | 49.5% | 100.0% | 8.33e+05 | 99.7% | 2.938 | 1.454 | 1.289 | 4.38e+05 |
| pix2nvs | 3.19e+05 | 85.48 | 49.7% | 95.7% | 6.35e+05 | 92.8% | 1.632 | 0.779 | 0.982 | 2.54e+05 |
| v2e | 2.22e+06 | 580.8 | 50.2% | 95.7% | 8.29e+04 | 95.0% | 11.34 | 5.294 | 0.128 | 2.22e+06 |
| vid2e | 2.81e+06 | 731.2 | 50.1% | 96.0% | 5.18e+04 | 96.0% | 14.37 | 6.665 | 0.080 | 2.79e+06 |

## Critere de proximite

Pour eviter toute ambiguite, le meme critere est applique partout dans le rapport:

- pour un ratio, le plus proche de VIVID minimise `abs(ratio - 1)`;
- pour une difference en points de pourcentage, le plus proche minimise `abs(diff_pp)`.

Application globale du critere:

| Metrique | Plus proche | Valeur | Distance | Critere |
| --- | --- | --- | --- | --- |
| events/s | pix2nvs | 1.632 | 0.632 | abs(ratio - 1) |
| events/pixel | pix2nvs | 0.779 | 0.221 | abs(ratio - 1) |
| delai | pix2nvs | 0.982 | 0.018 | abs(ratio - 1) |
| ON ratio | iebcs | 7.151 | 7.151 | abs(diff_pp) |
| pixels utilises | dvs_voltmeter | 0.126 | 0.126 | abs(diff_pp) |

## Volume d'evenements

VIVID produit en moyenne `1.95e+05` events/s. `pix2nvs` reste le plus proche en volume moyen, meme s'il reste au-dessus de VIVID avec un facteur `1.632`.
`v2e` et `vid2e` sont nettement plus eleves: environ `11.34`x et `14.37`x VIVID.
Cela suggere une generation d'evenements plus dense, probablement liee aux seuils, au bruit ou a l'interpolation temporelle.

![events/s](comparaison/figures/01_events_per_second.png)

## Evenements par pixel

Cette metrique corrige la difference de resolution entre VIVID et les simulateurs.
Sur la moyenne globale, `pix2nvs` est le plus proche de VIVID avec un facteur `0.779`: il est legerement en dessous de VIVID, alors que `iebcs` est au-dessus avec un facteur `1.454`.
`iebcs` reste interessant car il garde une couverture du capteur tres complete, mais il n'est pas le plus proche globalement sur `events/pixel`.
`v2e` et `vid2e` restent largement au-dessus, donc l'ecart de volume ne vient pas seulement du nombre de pixels du capteur.

![events/pixel](comparaison/figures/02_events_per_pixel.png)

## Ratio ON

VIVID a un ratio ON plus bas que la plupart des simulateurs. Les simulateurs tendent souvent vers une polarite plus proche de 50/50.
Cette difference peut indiquer que les modeles de seuil ON/OFF ou de contraste ne reproduisent pas exactement le desequilibre de VIVID.

![ON ratio](comparaison/figures/03_on_fraction.png)

## Pixels utilises

La plupart des methodes activent une grande partie du capteur, mais `pix2nvs`, `v2e` et `vid2e` utilisent moins de pixels dans certaines conditions, surtout dans les scenes sombres.
Cette metrique aide a distinguer un simulateur qui produit beaucoup d'evenements partout d'un simulateur qui concentre l'activite sur moins de pixels.

![pixels utilises](comparaison/figures/04_active_pixel_fraction.png)

## Delai inter-event par pixel

Le delai inter-event complete la lecture du volume: si un simulateur produit beaucoup plus d'evenements, on s'attend souvent a des delais plus courts.
`v2e` et `vid2e` ont effectivement des delais beaucoup plus courts que VIVID, ce qui confirme une dynamique plus dense.
`pix2nvs` est proche de VIVID sur le delai moyen, mais la remarque sur l'ordre temporel reste importante.

![delai inter-event par pixel](comparaison/figures/05_delay_inter_event_per_pixel.png)

## Events/s par fenetre temporelle

Cette figure montre si les pics d'activite arrivent globalement aux memes moments.
Elle evite de conclure uniquement a partir d'une moyenne: deux simulateurs peuvent avoir un volume moyen proche mais des pics temporels mal places.

![events/s par fenetre](comparaison/figures/06_events_per_second_by_temporal_window.png)

## Analyse par condition

Les moyennes globales cachent une partie du comportement. Ici, chaque condition est comparee a VIVID dans la meme condition.

| Condition | Source | events/s vs VIVID | events/pixel vs VIVID | ON diff pp | pixels diff pp | delai vs VIVID |
| --- | --- | --- | --- | --- | --- | --- |
| dark | vivid | 1.000 | 1.000 | 0.000 | 0.000 | 1.000 |
| dark | dvs_voltmeter | 1.024 | 0.505 | 15.79 | -0.002 | 2.815 |
| dark | iebcs | 0.981 | 0.505 | 12.99 | 0.002 | 2.237 |
| dark | pix2nvs | 0.283 | 0.154 | 8.145 | -14.41 | 1.450 |
| dark | v2e | 3.215 | 1.551 | 9.097 | -14.20 | 0.169 |
| dark | vid2e | 5.978 | 2.806 | 8.667 | -13.48 | 0.081 |
| global | vivid | 1.000 | 1.000 | 0.000 | 0.000 | 1.000 |
| global | dvs_voltmeter | 2.902 | 1.504 | 11.31 | 0.000 | 0.591 |
| global | iebcs | 1.210 | 0.663 | 6.167 | 0.000 | 1.687 |
| global | pix2nvs | 0.829 | 0.434 | 8.093 | 0.000 | 2.194 |
| global | v2e | 5.554 | 2.865 | 8.300 | 0.000 | 0.382 |
| global | vid2e | 6.550 | 3.281 | 8.277 | 0.000 | 0.361 |
| local | vivid | 1.000 | 1.000 | 0.000 | 0.000 | 1.000 |
| local | dvs_voltmeter | 25.38 | 12.64 | 5.164 | 0.422 | 0.075 |
| local | iebcs | 15.64 | 8.279 | 0.690 | 0.422 | 0.128 |
| local | pix2nvs | 8.481 | 4.334 | 3.673 | 0.422 | 0.205 |
| local | v2e | 59.24 | 29.48 | 3.515 | 0.422 | 0.034 |
| local | vid2e | 72.70 | 36.06 | 3.543 | 0.422 | 0.030 |
| varying | vivid | 1.000 | 1.000 | 0.000 | 0.000 | 1.000 |
| varying | dvs_voltmeter | 5.901 | 2.829 | 16.56 | 0.000 | 0.303 |
| varying | iebcs | 5.297 | 2.540 | 11.97 | 0.000 | 0.346 |
| varying | pix2nvs | 2.286 | 1.098 | 13.87 | 0.000 | 0.786 |
| varying | v2e | 15.66 | 7.522 | 15.40 | 0.000 | 0.114 |
| varying | vid2e | 23.61 | 11.08 | 15.39 | 0.000 | 0.079 |

Meilleurs simulateurs par condition avec le critere uniforme:

| Condition | Metrique | Plus proche | Valeur | Distance | Critere |
| --- | --- | --- | --- | --- | --- |
| dark | events/s | iebcs | 0.981 | 0.019 | abs(ratio - 1) |
| dark | events/pixel | dvs_voltmeter | 0.505 | 0.495 | abs(ratio - 1) |
| dark | delai | pix2nvs | 1.450 | 0.450 | abs(ratio - 1) |
| dark | ON ratio | pix2nvs | 8.145 | 8.145 | abs(diff_pp) |
| dark | pixels utilises | dvs_voltmeter | -0.002 | 0.002 | abs(diff_pp) |
| global | events/s | pix2nvs | 0.829 | 0.171 | abs(ratio - 1) |
| global | events/pixel | iebcs | 0.663 | 0.337 | abs(ratio - 1) |
| global | delai | dvs_voltmeter | 0.591 | 0.409 | abs(ratio - 1) |
| global | ON ratio | iebcs | 6.167 | 6.167 | abs(diff_pp) |
| global | pixels utilises | dvs_voltmeter | 0.000 | 0.000 | abs(diff_pp) |
| local | events/s | pix2nvs | 8.481 | 7.481 | abs(ratio - 1) |
| local | events/pixel | pix2nvs | 4.334 | 3.334 | abs(ratio - 1) |
| local | delai | pix2nvs | 0.205 | 0.795 | abs(ratio - 1) |
| local | ON ratio | iebcs | 0.690 | 0.690 | abs(diff_pp) |
| local | pixels utilises | dvs_voltmeter | 0.422 | 0.422 | abs(diff_pp) |
| varying | events/s | pix2nvs | 2.286 | 1.286 | abs(ratio - 1) |
| varying | events/pixel | pix2nvs | 1.098 | 0.098 | abs(ratio - 1) |
| varying | delai | pix2nvs | 0.786 | 0.214 | abs(ratio - 1) |
| varying | ON ratio | iebcs | 11.97 | 11.97 | abs(diff_pp) |
| varying | pixels utilises | dvs_voltmeter | 0.000 | 0.000 | abs(diff_pp) |

Lecture synthetique:

Ici, `plus proche` signifie: ratio le plus proche de `1` pour `events/s`, `events/pixel` et le delai; ecart le plus proche de `0` pour le ratio ON.

- `dark`: plus proche en `events/s`: `iebcs`; plus proche en `events/pixel`: `dvs_voltmeter`; plus proche en ratio ON: `pix2nvs`.
- `global`: plus proche en `events/s`: `pix2nvs`; plus proche en `events/pixel`: `iebcs`; plus proche en ratio ON: `iebcs`.
- `local`: plus proche en `events/s`: `pix2nvs`; plus proche en `events/pixel`: `pix2nvs`; plus proche en ratio ON: `iebcs`.
- `varying`: plus proche en `events/s`: `pix2nvs`; plus proche en `events/pixel`: `pix2nvs`; plus proche en ratio ON: `iebcs`.

`dark` met davantage en evidence le bruit et les seuils de declenchement. `global` et `local` revelent surtout les ecarts de volume. `varying` teste la robustesse quand l'intensite change au cours du temps.

## Analyse par regime

Les regimes `aggressive`, `robust` et `unstable` donnent une deuxieme lecture des memes donnees.

| Regime | Source | events/s vs VIVID | events/pixel vs VIVID | ON diff pp | pixels diff pp | delai vs VIVID |
| --- | --- | --- | --- | --- | --- | --- |
| aggressive | vivid | 1.000 | 1.000 | 0.000 | 0.000 | 1.000 |
| aggressive | dvs_voltmeter | 4.548 | 1.986 | 9.872 | 0.028 | 0.723 |
| aggressive | iebcs | 2.192 | 0.940 | 6.306 | 0.032 | 2.362 |
| aggressive | pix2nvs | 1.356 | 0.590 | 7.607 | -4.329 | 2.689 |
| aggressive | v2e | 10.06 | 4.375 | 7.936 | -2.793 | 0.241 |
| aggressive | vid2e | 12.12 | 5.050 | 7.835 | -2.844 | 0.149 |
| robust | vivid | 1.000 | 1.000 | 0.000 | 0.000 | 1.000 |
| robust | dvs_voltmeter | 6.712 | 3.000 | 12.92 | 0.263 | 1.122 |
| robust | iebcs | 5.111 | 2.202 | 7.999 | 0.263 | 0.868 |
| robust | pix2nvs | 2.386 | 1.048 | 7.415 | -2.935 | 0.593 |
| robust | v2e | 15.57 | 6.821 | 8.149 | -4.221 | 0.097 |
| robust | vid2e | 21.77 | 9.205 | 8.000 | -3.837 | 0.063 |
| unstable | vivid | 1.000 | 1.000 | 0.000 | 0.000 | 1.000 |
| unstable | dvs_voltmeter | 4.848 | 2.056 | 10.69 | 0.042 | 2.980 |
| unstable | iebcs | 2.555 | 1.052 | 6.865 | 0.042 | 2.092 |
| unstable | pix2nvs | 1.522 | 0.640 | 7.041 | -5.751 | 1.368 |
| unstable | v2e | 10.35 | 4.340 | 7.245 | -5.362 | 0.170 |
| unstable | vid2e | 12.64 | 5.165 | 7.113 | -5.102 | 0.101 |

Meilleurs simulateurs par regime avec le critere uniforme:

| Regime | Metrique | Plus proche | Valeur | Distance | Critere |
| --- | --- | --- | --- | --- | --- |
| aggressive | events/s | pix2nvs | 1.356 | 0.356 | abs(ratio - 1) |
| aggressive | events/pixel | iebcs | 0.940 | 0.060 | abs(ratio - 1) |
| aggressive | delai | dvs_voltmeter | 0.723 | 0.277 | abs(ratio - 1) |
| aggressive | ON ratio | iebcs | 6.306 | 6.306 | abs(diff_pp) |
| aggressive | pixels utilises | dvs_voltmeter | 0.028 | 0.028 | abs(diff_pp) |
| robust | events/s | pix2nvs | 2.386 | 1.386 | abs(ratio - 1) |
| robust | events/pixel | pix2nvs | 1.048 | 0.048 | abs(ratio - 1) |
| robust | delai | dvs_voltmeter | 1.122 | 0.122 | abs(ratio - 1) |
| robust | ON ratio | pix2nvs | 7.415 | 7.415 | abs(diff_pp) |
| robust | pixels utilises | dvs_voltmeter | 0.263 | 0.263 | abs(diff_pp) |
| unstable | events/s | pix2nvs | 1.522 | 0.522 | abs(ratio - 1) |
| unstable | events/pixel | iebcs | 1.052 | 0.052 | abs(ratio - 1) |
| unstable | delai | pix2nvs | 1.368 | 0.368 | abs(ratio - 1) |
| unstable | ON ratio | iebcs | 6.865 | 6.865 | abs(diff_pp) |
| unstable | pixels utilises | dvs_voltmeter | 0.042 | 0.042 | abs(diff_pp) |

Lecture synthetique:

Le meme critere est utilise: ratio le plus proche de `1`, ou ecart ON le plus proche de `0`.

- `aggressive`: plus proche en `events/s`: `pix2nvs`; plus proche en `events/pixel`: `iebcs`; plus proche en ratio ON: `iebcs`.
- `robust`: plus proche en `events/s`: `pix2nvs`; plus proche en `events/pixel`: `pix2nvs`; plus proche en ratio ON: `pix2nvs`.
- `unstable`: plus proche en `events/s`: `pix2nvs`; plus proche en `events/pixel`: `iebcs`; plus proche en ratio ON: `iebcs`.

## Conclusion

Globalement, le plus proche de VIVID est `pix2nvs` pour `events/s`, `pix2nvs` pour `events/pixel`, `pix2nvs` pour le delai, `iebcs` pour le ratio ON, et `dvs_voltmeter` pour la couverture de pixels.
`pix2nvs` ressort donc tres proche sur plusieurs mesures globales. Cette proximite doit toutefois etre lue avec prudence, car ses timestamps ne sont pas toujours ordonnes et sa couverture de pixels est plus faible.
`iebcs` n'est pas le meilleur sur le volume global, mais il apparait comme un compromis propre: volume modere, ratio ON relativement proche, et couverture quasi complete du capteur.
`dvs_voltmeter` couvre tres bien le capteur, mais son volume et son ratio ON sont plus eloignes de VIVID.
`v2e` et `vid2e` produisent beaucoup plus d'evenements que VIVID et des delais inter-event plus courts, ce qui indique une dynamique plus dense.

## Limites possibles

- VIVID est traite comme reference, mais cela ne prouve pas qu'il soit une verite absolue pour toutes les scenes.
- Les simulateurs n'ont pas forcement ete calibres avec les memes seuils, bruit, latence ou modele de capteur.
- `events/pixel` corrige la resolution, mais ne corrige pas tous les effets lies a la geometrie ou au champ de vue.
- Les timestamps non ordonnes de `pix2nvs` limitent les conclusions temporelles fines.
- Les figures temporelles sont moyennees sur les sequences; une analyse plus poussee pourrait regarder chaque sequence separement.

## Sources utilisees pour interpreter les simulateurs

- v2e: https://github.com/SensorsINI/v2e
- IEBCS: https://github.com/neuromorphicsystems/IEBCS
- DVS-Voltmeter: https://www.ecva.net/papers/eccv_2022/papers_ECCV/papers/136670571.pdf
- PIX2NVS: https://discovery.ucl.ac.uk/id/eprint/10056312/
- Vid2E: https://openaccess.thecvf.com/content_CVPR_2020/papers/Gehrig_Video_to_Events_Recycling_Video_Datasets_for_Event_Cameras_CVPR_2020_paper.pdf
