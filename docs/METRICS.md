# Métriques de comparaison

La comparaison est volontairement centrée sur des métriques simples et lisibles.

## Métriques principales

### Événements par seconde

```text
events/s = n_events / durée
```

Cette métrique mesure le volume moyen d’événements produit par une méthode.

### Événements par pixel

```text
events/pixel = n_events / (largeur * hauteur)
```

Cette métrique normalise le nombre d’événements par la taille du capteur.

### Ratio ON

```text
ON ratio = n_ON / n_events
```

Cette métrique mesure l’équilibre entre événements ON et OFF.

### Pixels utilisés

```text
pixels utilisés = pixels_actifs / pixels_totaux
```

Cette métrique indique la fraction du capteur qui produit au moins un événement.

## Contrôles temporels

### Délai inter-événement par pixel

```text
délai_pixel = (t_dernier - t_premier) / (n_events_pixel - 1)
```

Le délai est calculé pour les pixels ayant au moins deux événements.

### Events/s par fenêtre temporelle

Le temps est découpé en fenêtres régulières. Le script calcule ensuite le nombre d’événements par seconde dans chaque fenêtre.

Cette courbe permet de vérifier si les pics temporels suivent la même forme que la référence ViViD++.

## Lecture rapide

Une simulation proche de ViViD++ doit idéalement présenter :

```text
events/s proche de ViViD++
events/pixel proche de ViViD++
ratio ON proche de ViViD++
fraction de pixels actifs cohérente
courbe temporelle proche de ViViD++
```

Les métriques doivent être interprétées ensemble. Un simulateur peut produire le bon volume moyen, mais avoir une mauvaise dynamique temporelle.
