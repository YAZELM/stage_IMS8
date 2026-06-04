# Rapport exemple de comparaison fondamentale

## Analyse

Cette section reprend l’analyse complète produite par le script de comparaison fondamentale. Elle est intégrée au README principal afin que la méthode, les résultats et l’interprétation soient visibles directement depuis la page GitHub du projet.

### Ce qui est comparé

La comparaison garde quatre métriques principales :

- `events/s` : nombre d’événements par seconde.
- `events/pixel` : nombre total d’événements divisé par le nombre total de pixels du capteur.
- `ON ratio` : proportion d’événements ON, calculée par `n_ON / n_events`.
- `pixels utilisés` : proportion de pixels qui ont produit au moins un événement.

Deux contrôles temporels sont ajoutés :

- `délai inter-événement par pixel` : calculé en parcourant les pixels du capteur.
- `events/s par fenêtre` : calculé avec des fenêtres temporelles régulières.

ViViD++ est la référence de comparaison. Il apparaît aussi dans les figures comme une source à part entière.

### Formules utilisées

```text
events/s = n_events / durée
events/pixel = n_events / (largeur * hauteur)
ON ratio = n_ON / n_events
pixels utilisés = pixels_actifs / pixels_totaux
délai_pixel = (t_dernier - t_premier) / (n_events_pixel - 1)
```

Le délai inter-événement par pixel est calculé uniquement pour les pixels ayant au moins deux événements.

Dans l’exemple fourni, la résolution utilisée est :

```text
ViViD++ : 240 × 180
simulateurs : 346 × 260
```

Pour le délai, le script crée une case pour chaque pixel du capteur. Les pixels avec moins de deux événements sont comptés dans le nombre de pixels actifs, mais ils n’ont pas de délai inter-événement défini.

### Vérification rapide

Dans l’exemple fourni :

```text
Fichiers analysés : 60
Fichiers invalides : 0
Fichiers avec timestamps non ordonnés sur échantillon : 10
```

Les timestamps non ordonnés concernent `pix2nvs`. Les quatre métriques principales restent utilisables, car elles ne dépendent pas de l’ordre des lignes. En revanche, une analyse temporelle fine nécessite de contrôler ou trier les timestamps.

### Résultats moyens

| Source | events/s | events/pixel | ON ratio | pixels utilisés | délai/pixel | pixels avec délai | events/s vs VIVID | events/pixel vs VIVID | délai vs VIVID | RMSE fenêtres |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| vivid | 1.95e+05 | 109.7 | 42.4% | 99.9% | 6.47e+05 | 99.6% | 1.000 | 1.000 | 1.000 | 0.000 |
| dvs_voltmeter | 9.99e+05 | 262.5 | 53.7% | 100.0% | 9.55e+05 | 98.2% | 5.112 | 2.393 | 1.476 | 8.82e+05 |
| iebcs | 5.74e+05 | 159.5 | 49.5% | 100.0% | 8.33e+05 | 99.7% | 2.938 | 1.454 | 1.289 | 4.38e+05 |
| pix2nvs | 3.19e+05 | 85.48 | 49.7% | 95.7% | 6.35e+05 | 92.8% | 1.632 | 0.779 | 0.982 | 2.54e+05 |
| v2e | 2.22e+06 | 580.8 | 50.2% | 95.7% | 8.29e+04 | 95.0% | 11.34 | 5.294 | 0.128 | 2.22e+06 |
| vid2e | 2.81e+06 | 731.2 | 50.1% | 96.0% | 5.18e+04 | 96.0% | 14.37 | 6.665 | 0.080 | 2.79e+06 |

### Interprétation

- ViViD++ produit en moyenne environ `1.95e5 events/s` et `109.7 events/pixel`.
- `pix2nvs` est le plus proche de ViViD++ en nombre moyen d’événements par seconde.
- `pix2nvs` utilise cependant moins de pixels que ViViD++ et ses timestamps doivent être contrôlés avant une analyse temporelle fine.
- `iebcs` présente le comportement global le plus équilibré sur les métriques simples : volume modéré, ratio ON proche, et presque tous les pixels sont utilisés.
- `dvs_voltmeter` active presque tout le capteur, mais produit environ cinq fois plus d’événements par seconde que ViViD++ et présente un ratio ON plus élevé.
- `v2e` et `vid2e` produisent beaucoup plus d’événements que ViViD++ dans ces conditions.
- Le délai inter-événement par pixel permet de vérifier si une surproduction correspond aussi à des événements beaucoup plus rapprochés dans le temps.
- La figure `events/s par fenêtre` permet de voir si les pics temporels suivent la même forme que ViViD++ ou seulement un volume moyen proche.

Conclusion de l’exemple :

```text
Si le critère principal est le volume d’événements, pix2nvs est le plus proche.
Si le critère principal est un comportement global stable sur les métriques simples, iebcs est le candidat le plus cohérent.
```

Cette conclusion dépend des paramètres utilisés et doit être réévaluée pour chaque nouvelle configuration.

### Hypothèses d’explication

- `v2e` et `vid2e` peuvent surproduire parce qu’ils utilisent des modèles ou interpolations qui rendent les variations temporelles plus denses.
- `dvs_voltmeter` ajoute une modélisation stochastique du capteur, ce qui peut augmenter l’activité et la couverture spatiale.
- `iebcs` semble plus contraint par ses paramètres de capteur : seuils, latence, jitter et période réfractaire.
- `pix2nvs` est proche en volume, mais son ordre temporel doit être vérifié plus soigneusement.

### Figures de l’exemple

#### Nombre d’événements par seconde

![Nombre d'événements par seconde](docs/example_comparison/figures/01_events_per_second.png)

#### Nombre d’événements par pixel

![Nombre d'événements par pixel](docs/example_comparison/figures/02_events_per_pixel.png)

#### Ratio d’événements ON

![Ratio ON](docs/example_comparison/figures/03_on_fraction.png)

#### Pixels actifs sur pixels totaux

![Pixels actifs](docs/example_comparison/figures/04_active_pixel_fraction.png)

#### Délai inter-événement moyen par pixel

![Délai inter-événement](docs/example_comparison/figures/05_delay_inter_event_per_pixel.png)

#### Events/s par fenêtre temporelle

![Events/s par fenêtre temporelle](docs/example_comparison/figures/06_events_per_second_by_temporal_window.png)

### Métriques utiles à ajouter ensuite

- `Hot pixels` : utile pour séparer le bruit de capteur de l’activité utile.
- Sensibilité aux seuils ON/OFF : utile car plusieurs simulateurs dépendent fortement du seuil de contraste.
- Comparaison spatiale par carte d’activité : utile pour vérifier si les événements apparaissent aux mêmes endroits.
- Analyse par scène : utile pour savoir si un simulateur est meilleur dans les scènes sombres, locales, globales ou rapides.

### Sources utilisées pour interpréter les simulateurs

- v2e : https://github.com/SensorsINI/v2e
- IEBCS : https://github.com/neuromorphicsystems/IEBCS
- DVS-Voltmeter : https://www.ecva.net/papers/eccv_2022/papers_ECCV/papers/136670571.pdf
- PIX2NVS : https://discovery.ucl.ac.uk/id/eprint/10056312/
- Vid2E : https://openaccess.thecvf.com/content_CVPR_2020/papers/Gehrig_Video_to_Events_Recycling_Video_Datasets_for_Event_Cameras_CVPR_2020_paper.pdf
