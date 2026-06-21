# TB-303 Studio — Bass Line (émulateur acid + interface steampunk)

Un synthétiseur de basse *acid* inspiré de la Roland TB-303, écrit en Python pur
(numpy), avec une interface graphique « habillée » par une image (skin steampunk).
Le moteur sonore génère oscillateur → filtre passe-bas résonant → enveloppes →
séquenceur 16 pas, et l'interface superpose des contrôles fonctionnels sur l'image.

> **Honnêteté technique.** Ce n'est **pas** un clone au composant près du circuit
> de la TB-303. C'est une **émulation de caractère** : elle reproduit l'esprit
> (oscillateur saw/square anti-aliasé, filtre ladder résonant ~18 dB/oct balayé par
> l'enveloppe, accent, slide, séquenceur avec swing) mais le schéma électronique
> d'origine est approximé, pas copié. Aucune marque, aucun logo ni échantillon
> Roland n'est utilisé — le design du panneau est original.

---

## Sommaire

1. [Contenu du dossier](#contenu-du-dossier)
2. [Prérequis et installation](#prérequis-et-installation)
3. [Démarrage rapide](#démarrage-rapide)
4. [L'interface](#linterface)
5. [Programmer un pattern](#programmer-un-pattern)
6. [Référence des potards](#référence-des-potards)
7. [Menus : Scale, Play Mode, Preset](#menus--scale-play-mode-preset)
8. [Le moteur de synthèse](#le-moteur-de-synthèse)
9. [Notation des patterns](#notation-des-patterns)
10. [Utiliser le moteur comme bibliothèque](#utiliser-le-moteur-comme-bibliothèque)
11. [Le système de skin (image + carte de coordonnées)](#le-système-de-skin-image--carte-de-coordonnées)
12. [Créer un nouveau skin](#créer-un-nouveau-skin)
13. [Dépannage](#dépannage)
14. [Notes fichier par fichier](#notes-fichier-par-fichier)

---

## Contenu du dossier

| Fichier | Rôle |
|---|---|
| `tb303.py` | Moteur de synthèse + séquenceur (numpy seul). Aucune dépendance GUI. |
| `tb303_studio.py` | Interface graphique « skin » : charge l'image et superpose les contrôles. |
| `tb303_skin.png` | Image d'habillage (panneau steampunk, cases et valeurs vides). |

Les **trois fichiers doivent être dans le même dossier**. `tb303_studio.py` importe
`tb303.py` et charge `tb303_skin.png` par défaut.

---

## Prérequis et installation

### Dépendances

| Paquet | Pourquoi | Obligatoire ? |
|---|---|---|
| **numpy** | Synthèse audio | Oui |
| **Pillow** (+ ImageTk) | Charger et afficher l'image de skin | Oui (pour le GUI) |
| **Tkinter** | Fenêtre et widgets | Oui (souvent déjà là) |
| **pygame** | Lecture audio temps réel (RUN/STOP) | Optionnel — sans lui, **SAVE WAV** fonctionne quand même |

### Installer — règle d'or

Installe **dans le même Python que celui qui lance le script**. Le plus sûr :

```bash
python3 -m pip install numpy pillow pygame
```

En faisant `python3 -m pip`, les paquets vont forcément dans l'interpréteur que
`python3 tb303_studio.py` utilise — pas de question d'environnement à se poser.

### Selon le système

**Ubuntu / Debian (Python système).** Le plus propre passe par apt — il vise pile le
`python3` système et fournit `ImageTk` (souvent manquant via pip seul) :

```bash
sudo apt install python3-numpy python3-pygame python3-pil python3-pil.imagetk python3-tk
```

> Le paquet **`python3-pil.imagetk`** est important : c'est lui qui apporte `ImageTk`.
> Sans lui, Pillow seul ne suffit pas avec Tkinter et la fenêtre ne s'affiche pas.

Si pip refuse avec « externally-managed-environment » (Ubuntu récent), ajoute
`--break-system-packages` ou passe par un venv.

**conda (ex. environnement `xtts`).** Active l'environnement où tu lances le script,
puis installe dedans :

```bash
conda activate mon_env
pip install pygame pillow numpy
```

**WSL / WSLg (Windows).** Le son passe par WSLg/PulseAudio. **Aucune variable à régler
à la main** : au démarrage, si `tb303_studio.py` détecte `/mnt/wslg/PulseServer`, il
branche tout seul `SDL_AUDIODRIVER=pulseaudio` et le bon `PULSE_SERVER`.

### Vérifier l'installation

```bash
python3 -c "import sys, numpy, PIL, pygame; print(sys.executable); print('pygame', pygame.__version__)"
```

Si le chemin affiché est bien ton interpréteur et qu'aucune erreur n'apparaît, tu es prêt.

---

## Démarrage rapide

```bash
python3 tb303_studio.py
```

À l'ouverture, l'interface affiche déjà le pattern de démo. Regarde le **texte de
statut** (en bas) :

- **« Pret »** → le moteur audio est actif, RUN va jouer.
- **« pygame absent »** → installe pygame pour le son temps réel (SAVE WAV marche déjà).
- **« audio KO (…) »** → le moteur audio n'a pas pu s'initialiser ; le message entre
  parenthèses indique la cause.

Pour charger une autre image de skin :

```bash
python3 tb303_studio.py mon_autre_skin.png
```

---

## L'interface

Tout est cliquable directement sur l'image.

- **WAVEFORM (saw / sqr)** — choisit la forme d'onde de l'oscillateur (dent de scie ou carré).
- **6 potards du haut** — TUNING, CUT OFF, RESONANCE, ENV MOD, DECAY, ACCENT.
- **4 potards du bas** — TEMPO, DIST(orsion), VOLUME, SHUFFLE.
- **SCALE / PLAY MODE / PRESET** — trois menus déroulants.
- **PATTERN 1–8** — huit banques de patterns indépendantes.
- **RUN / STOP** — lecture en boucle / arrêt.
- **Clavier** — clique une touche pour poser une note sur le pas sélectionné.
- **ACCENT / SLIDE / OCT↓ / OCT↑ / REST** — modificateurs du pas sélectionné.
- **Bande des 16 cases** — les 16 pas du séquenceur ; clique une case pour la sélectionner
  (cadre ambré). Chaque case montre sa note vivante (ex. `C2`, avec `+` accent, `~` slide).
- **SAVE WAV / CLEAR / DEMO** — exporter en .wav / tout effacer / recharger la démo.

**Réglage d'un potard :** molette de la souris au-dessus, ou clic-glissé vertical.

---

## Programmer un pattern

1. **Clique une case** dans la bande des 16 pas (elle se cadre en ambre).
2. **Clique une touche du clavier** → la note se pose sur ce pas, et la sélection
   avance automatiquement au pas suivant. (Tu peux donc enchaîner les notes au clavier.)
3. Pour modifier un pas précis : sélectionne-le, puis :
   - **ACCENT** → accentue le pas (plus fort, filtre plus ouvert). Marqué `+`.
   - **SLIDE** → glissando vers la note suivante (legato/portamento). Marqué `~`.
   - **OCT↓ / OCT↑** → descend / monte la note d'une octave.
   - **REST** → silence (efface la note du pas).
4. **PATTERN 1–8** : huit banques. Changer de banque sauvegarde l'actuelle et charge
   l'autre — pratique pour A/B ou construire un morceau.
5. **CLEAR** vide le pattern courant ; **DEMO** recharge le pattern d'exemple.
6. **RUN** joue en boucle ; tu peux tourner les potards **pendant** la lecture, le son
   se met à jour à chaque changement.

---

## Sauvegarder et rappeler un projet (`.tb303`)

En plus de l'export audio (WAV), tu peux enregistrer **tout l'état éditable** dans un
fichier projet `nom.tb303` et le **recharger tel quel** plus tard — avec exactement les
mêmes positions de potards et tous les paramètres.

Via le menu **Fichier** (en haut de la fenêtre) ou les raccourcis :

| Action | Menu | Raccourci |
|---|---|---|
| Sauvegarder le projet | Fichier → Sauvegarder projet… | **Ctrl+S** |
| Recharger un projet | Fichier → Ouvrir projet… | **Ctrl+O** |
| Exporter l'audio | Fichier → Exporter WAV… (ou bouton SAVE WAV) | — |

Le fichier `.tb303` (format JSON lisible) contient : **les 10 potards**, la **forme d'onde**,
les menus **Scale / Play Mode / Preset**, la **banque courante**, et les **8 banques** de
pattern complètes (notes, accents, slides). Le rouvrir restitue tout d'un coup.

> À ne pas confondre : **SAVE WAV** exporte le *son* (non rééditable) ; **Sauvegarder
> projet** enregistre la *session* (rééditable, rejouable, modifiable).

---

## Référence des potards

| Potard | Plage | Défaut | Effet |
|---|---|---|---|
| **TUNING** | 400–480 | 440 | Accord global fin (≈ ±1,5 demi-ton). Décale la hauteur de tout, subtilement. |
| **CUT OFF** | 0–1 | 0,40 | Fréquence de coupure du filtre. Très audible : ouvre/ferme le son (30 Hz → 10 kHz). |
| **RESONANCE** | 0–1 | 0,10 | Pic résonant au cutoff. Monté haut, donne le « squelch » acid (jusqu'à friser l'auto-oscillation). |
| **ENV MOD** | 0–1 | 0,12 | Quantité dont l'enveloppe ouvre le filtre à chaque note (le « wow » du 303). |
| **DECAY** | 0–1 | 0,40 | Durée du balayage du filtre par note (≈ 0,04 → 1,6 s). |
| **ACCENT** | 0–1 | 0,30 | Intensité des pas accentués. **N'agit que sur les pas marqués `+`** (sinon : aucun effet, c'est normal). |
| **TEMPO** | 60–200 | 130 | Tempo en BPM. |
| **DIST** | 0–1 | 0,00 | Saturation (waveshaping tanh) après le filtre. Ajoute du grain/grognement. |
| **VOLUME** | 0–1 | 0,90 | Niveau de sortie (lecture **et** export). |
| **SHUFFLE** | 0–0,66 | 0,00 | Swing : décale un pas sur deux pour un groove ternaire. Audible surtout en 1/16. |

**Le combo gagnant pour le son acid :** RESONANCE haute (0,8–1,0) + CUT OFF bas (~0,3) +
ENV MOD élevé, puis balaie CUT OFF pendant que ça joue.

---

## Menus : Scale, Play Mode, Preset

**SCALE** (subdivision rythmique des pas) :

| Choix | Pas par temps |
|---|---|
| 1/8 | 2 |
| 1/8T | 3 (triolet) |
| 1/16 | 4 |
| 1/16T | 6 (triolet) |
| 1/32 | 8 |

**PLAY MODE** (ordre de lecture des 16 pas) : `Forward`, `Reverse`, `Fwd&Rev`
(aller-retour), `Invert` (inverse haut/bas), `Random`.

**PRESET** (réglages de départ rapides) :

| Preset | Onde | Cutoff | Reso | EnvMod | Decay | Accent | Dist |
|---|---|---|---|---|---|---|---|
| Classic Bass | carré | 0,40 | 0,10 | 0,12 | 0,40 | 0,30 | 0,00 |
| Acid | scie | 0,30 | 0,84 | 0,65 | 0,55 | 0,70 | 0,28 |
| Sub Bass | carré | 0,24 | 0,06 | 0,06 | 0,55 | 0,30 | 0,00 |
| Rubber | scie | 0,36 | 0,45 | 0,35 | 0,45 | 0,45 | 0,00 |

---

## Le moteur de synthèse

Chaîne de traitement, dans l'ordre :

1. **Oscillateur** — dent de scie ou carré, anti-aliasé par **PolyBLEP** (pas
   d'aliasing métallique sur les notes hautes).
2. **Filtre passe-bas type 303** — un **ladder à 4 étages** dont la **sortie est prise
   au 3e pôle**, ce qui donne une pente d'environ **18 dB/oct** (plus claire et nasillarde
   que les 24 dB/oct d'un Moog — la signature du 303). La **contre-réaction vient du 4e
   pôle** (déphasage nécessaire pour résonner), avec une **saturation tanh** sur
   l'entrée et la boucle : la résonance peut monter jusqu'à friser l'auto-oscillation,
   et la saturation apporte le grain.
3. **Enveloppe de filtre** — attaque rapide puis décroissance réglée par DECAY ; sa
   profondeur d'action sur le cutoff est réglée par ENV MOD. C'est elle qui crée le
   balayage « wow » caractéristique.
4. **Enveloppe d'amplitude (VCA)** — ouvre/ferme le niveau par note (gate), avec
   accent sur les pas marqués.
5. **Accent** — sur les pas `+`, augmente à la fois le niveau et l'ouverture du filtre.
6. **Slide** — sur les pas `~`, glissando de hauteur vers la note suivante (legato).
7. **Distorsion** — saturation tanh optionnelle après le filtre.
8. **Sortie** — normalisée puis mise au niveau VOLUME (sans renormalisation parasite,
   pour que VOLUME agisse réellement).

Le **séquenceur** gère 16 pas, les subdivisions (SCALE), le swing (SHUFFLE), les modes
de lecture (PLAY MODE) et la répétition (`repeats`).

---

## Notation des patterns

Un pattern est une liste de chaînes, une par pas :

| Écriture | Sens |
|---|---|
| `"C2"` | note (do, octave 2) |
| `"C#2"` / `"D#2"` … | dièses |
| `"C2+"` | note **accentuée** |
| `"C2~"` | note avec **slide** (vers la suivante) |
| `"."` | silence (rest) |

Octaves utilisées au clavier : 1, 2, 3. Exemple (le pattern de démo) :

```python
["C2", "C2~", "C3", "C2+", "D#2", "C2~", "C3", "A#1",
 "C2", "G2~", "C3+", "C2", "D#2", "C2", "A#1~", "C2+"]
```

---

## Utiliser le moteur comme bibliothèque

`tb303.py` s'utilise seul, sans interface :

```python
from tb303 import TB303, DEMO_PATTERN

tb = TB303(sample_rate=44100)

audio = tb.render(
    DEMO_PATTERN,        # liste de pas (voir notation)
    bpm=130,
    waveform="saw",      # "saw" ou "square"
    cutoff=0.32,         # 0..1
    resonance=0.85,      # 0..1
    env_mod=0.6,         # 0..1
    decay=0.5,           # 0..1
    accent=0.6,          # 0..1
    distortion=0.2,      # 0..1
    tuning=440.0,        # Hz (référence La)
    gate_len=0.55,       # longueur de note (0..1)
    repeats=4,           # nombre de boucles
    subdiv=4,            # 2,3,4,6,8 (cf. SCALE)
    swing=0.15,          # 0..0.66
    play_mode="forward", # forward/reverse/fwd_rev/invert/random
)

tb.write_wav(audio, "sortie.wav")   # stéréo 16 bits 44,1 kHz
```

Lancer le moteur directement génère un fichier de démo :

```bash
python3 tb303.py        # -> tb303_demo.wav
```

> **Note sur `write_wav`** : par défaut il **respecte le niveau** du signal fourni
> (pas de normalisation auto), pour que le potard VOLUME agisse. Si tu veux qu'il
> normalise, appelle `tb.write_wav(audio, "x.wav", normalize=True)`.

Helpers exposés : `note_to_freq(name, tuning)`, `parse_step(s)`,
`apply_play_mode(steps, mode)`, et la constante `DEMO_PATTERN`.

---

## Le système de skin (image + carte de coordonnées)

L'interface ne dessine pas ses contrôles : elle **affiche une image** (`tb303_skin.png`)
et **superpose les contrôles fonctionnels** à des coordonnées précises (aiguilles des
potards, texte des valeurs, menus, boutons cliquables, notes vivantes sur les cases).

Ces coordonnées sont stockées dans le dictionnaire **`SKIN_MAP`** en tête de
`tb303_studio.py` (en pixels de l'image native). Pour chaque potard : centre, rayon,
position du texte de valeur ; pour les boutons/cases : centre + demi-largeur/hauteur ;
pour le clavier et la bande : leur rectangle englobant.

L'image est affichée à sa taille native, ou réduite automatiquement pour tenir à
l'écran ; les coordonnées sont mises à l'échelle en conséquence, donc l'alignement
reste correct quelle que soit la taille d'écran.

---

## Créer un nouveau skin

Pour habiller le synthé avec une **autre image** (un cyberpunk, un classic…), il faut
fournir au programme les positions des contrôles. La méthode fiable :

1. Pars d'une image de panneau (même disposition générale : potards en haut, clavier,
   bande de 16 pas, etc.).
2. Sur **une copie**, dans un éditeur (GIMP, Photopea…), marque en **rouge vif (#FF0000)** :
   - un **cercle** au centre de chaque potard (10),
   - un **rectangle** autour de chaque contrôle (boutons, menus, banques, champs de
     valeur), un grand rectangle autour du **clavier**, un autour de la **bande des 16 cases**.
3. Ces marques rouges se détectent automatiquement par analyse d'image : on en extrait
   les coordonnées exactes, on **efface le rouge** (et on vide les cases/valeurs) pour
   obtenir l'habillage propre, et on remplit la `SKIN_MAP`.

> Astuce : marque sur une **copie de l'image finale**, ne régénère pas l'image avec les
> marques (sinon la mise en page bouge et les coordonnées ne correspondent plus).

C'est cette procédure qui a servi à fabriquer `tb303_skin.png` et sa carte actuelle.

---

## Dépannage

**RUN / STOP ne font rien.** Le bouton fonctionne, mais il n'a rien à jouer si le moteur
audio n'est pas actif. Clique RUN : une fenêtre t'expliquera la cause. En général il
manque **pygame** → `python3 -m pip install pygame`, puis relance. (SAVE WAV marche sans pygame.)

**Pas de son alors que le statut dit « Pret ».** Vérifie le volume système et, sur WSL,
que tu lances bien depuis WSL (et pas un shell où d'anciennes variables PulseAudio
traînent). Le routage WSLg est automatique si `/mnt/wslg/PulseServer` existe.

**La fenêtre ne s'ouvre pas / erreur ImageTk.** Sur Ubuntu, installe
`python3-pil.imagetk` (et `python3-tk`). `ImageTk` ne vient pas toujours avec Pillow seul.

**pip refuse (« externally-managed-environment »).** Ubuntu récent. Utilise apt
(`sudo apt install python3-…`), ou un venv, ou `pip install --break-system-packages`.

**Les contrôles tombent à côté de l'image.** Si tu utilises une image **différente** de
`tb303_skin.png` sans avoir adapté `SKIN_MAP`, les coordonnées ne correspondent pas.
Reprends la procédure « Créer un nouveau skin ».

**Le son est saturé / trop fort.** Baisse VOLUME, et n'empile pas DIST + RESONANCE au
maximum en même temps : chacun ajoute de l'énergie.

---

## Notes fichier par fichier

**`tb303.py`** — moteur sans dépendance GUI. Classe `TB303` (méthodes `render`,
`write_wav`), fonctions `note_to_freq`, `parse_step`, `apply_play_mode`, constante
`DEMO_PATTERN`, et un `main()` de démo. Modifiable indépendamment de l'interface.

**`tb303_studio.py`** — interface skin. Contient `SKIN_MAP` (coordonnées), le rendu des
overlays, la gestion des clics/molette, l'audio (pygame + routage WSLg auto), l'export
WAV et l'aperçu des notes au clavier. Importe `tb303.py`.

**`tb303_skin.png`** — image d'habillage 1817×866, cases et champs de valeur déjà vidés,
prête à recevoir les overlays.

---

*Émulation de caractère à but personnel/éducatif. Design de panneau original ; aucune
marque, logo ni échantillon Roland utilisé.*
