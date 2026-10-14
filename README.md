# ⚡ AizenSoundKeeper v2.0 🔊

> **Maintient tes baffes en vie, traverse les périphériques virtuels (SteelSeries Sonar) et optimise ton son à zéro latence.**

---

## 🎯 Ce que résout AizenSoundKeeper

Les amplificateurs Bluetooth (comme le récepteur **WZ-BT5.0**), les enceintes de monitoring et les sorties numériques (SPDIF / Optique / HDMI) disposent souvent d'un mode d'économie d'énergie agressif :
- Dès qu'un silence de 1 à 3 secondes survient dans une vidéo, l'amplificateur coupe le circuit de conversion.
- Dès qu'une personne reparle, le temps de réveil coupe le premier mot ("…onjour" au lieu de "Bonjour").

**AizenSoundKeeper** résout définitivement ce problème en injectant un signal de maintien continu et inaudible (-72 dB), couplé à un ciblage matériel intelligent et une chaîne DSP 100% zéro latence.

---

## 🚀 Démarrage rapide

1. Lance **`AizenSoundKeeper.exe`**
2. L'application démarre directement minimisée dans la **zone des icônes cachées** de la barre des tâches (icône verte ⚡).
3. **Double-clique sur l'icône** ou fais un **clic droit → ⚙ Paramètres…** pour ouvrir le panneau complet.

### 🔄 Démarrage automatique avec Windows (optionnel)
- Active-le en double-cliquant sur `install_autostart.bat`.
- Pour le retirer : double-clique sur `remove_autostart.bat`.

---

## 🛠 Fonctionnalités & Options

### 1. 🎯 Modes de ciblage des sorties
- **Primary (défaut)** : Envoie le signal uniquement sur la sortie principale active de Windows.
- **All** : Envoie le signal sur **toutes les sorties actives** (indispensable pour traverser les périphériques virtuels comme **SteelSeries Sonar**).
- **Digital** : Cible uniquement les sorties numériques (Sortie numérique / SPDIF / HDMI / Optique).
- **Analog** : Cible uniquement les sorties analogiques / Bluetooth (**WZ-BT5.0**, prises Jack).
- **Marked** : Cible uniquement les enceintes dont le nom contient un point d'exclamation `!` (ex. renommée en `!Mes Baffes` dans les paramètres audio Windows). Très propre pour épargner ton casque !
- **Manuel** : Coche manuellement un ou plusieurs périphériques dans la liste dédiée.

### 2. 💤 Gestion intelligente de la veille
- **Off** : AizenSoundKeeper tourne sans interruption.
- **SleepD** : Coupe le flux dès que ton écran s'éteint.
- **SleepL** : Coupe le flux dès que tu verrouilles ta session Windows (`Win + L`).
- **Sleepy** : Combine les deux — met tes baffes au repos dès que tu verrouilles ou que l'écran s'éteint.

### 3. 🎚 DSP Audio Temps Réel (Zéro Latence)
Tous les filtres sont basés sur des biquads IIR (Audio EQ Cookbook, RBJ) appliqués dans le callback audio direct :
- **Filtre Coupe-Bas (High-Pass Filter à 35–45 Hz)** : Élimine les sous-graves inaudibles sur des enceintes de bureau pour libérer la dynamique et éviter la saturation.
- **Bass Boost "Propre" (Low-Shelf 60–90 Hz)** : Renforce les graves avec compensation automatique de pré-gain négatif pour éliminer tout risque de clipping ou grésillement.
- **Boost de Présence / Clarté Vocale (+2 à +3 dB à 2.5–4 kHz)** : Fait ressortir les voix humaines au premier plan par rapport aux musiques de fond.
- **Smart Volume / Compresseur Dynamique** : Nivele les écarts entre dialogues faibles et explosions fortes (idéal pour YouTube / streaming nocturne).
- **Note Réducteur de Souffle IA** : Conformément à l'exigence de zéro latence, les filtres IA neuronaux (RNNoise/DeepFilterNet qui imposent ≥10 ms de bufferisation et décalage) ont été écartés au profit des solutions matérielles natives (ex. NVIDIA Broadcast / Krisp).

---

## 📦 Contenu du pack
- `AizenSoundKeeper.exe` : Exécutable autonome (aucun runtime requis)
- `aizensoundkeeper.ico` : Icône native de l'application
- `install_autostart.bat` : Script d'installation démarrage auto Windows
- `remove_autostart.bat` : Script de désinstallation démarrage auto
- `README.md` : Guide d'utilisation

---
*AizenOS HyperOS • Antigravity Engineering*
