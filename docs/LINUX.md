# Linux x86_64 — guide expérimental

Le build Linux natif est **expérimental**. La CI vérifie la compilation, le contenu AppImage, ses dépendances, le lancement des outils inclus et plusieurs contrats sans données du jeu. Cela ne constitue pas une validation complète du gameplay ni une garantie de fonctionnement sur tous les GPU.

## Configuration requise

- Linux x86_64 avec **GLIBC 2.35 ou plus récente** pour l'AppImage fournie.
- Vulkan 1.3, le chargeur Vulkan du système et un pilote compatible avec le GPU. La compatibilité du pilote doit être vérifiée sur la machine cible.
- Les capacités CPU requises par le niveau de code généré. Un CPU x86-64 plus ancien peut utiliser un niveau inférieur, avec des performances réduites ; AVX2/FMA/BMI2 permet le niveau v3 lorsqu'il est disponible.
- Intégration graphique/audio du système. L'AppImage contient SDL3, FFmpeg configuré sans les options GPL/nonfree et plusieurs bibliothèques de l'application ; le pilote GPU/Vulkan et les bibliothèques d'intégration graphique/audio restent fournis par l'hôte.

L'AppImage peut avoir besoin de FUSE 2. Si le lancement échoue uniquement parce que FUSE est indisponible, essayez le mode d'extraction intégré :

```bash
APPIMAGE_EXTRACT_AND_RUN=1 ./LetsGoRecomp-<version>-linux-x86_64.AppImage
```

L'archive `.tar.gz` est une autre option : extrayez-la, puis lancez `./LetsGoRecomp` depuis son dossier.

## Vérifier le téléchargement

Téléchargez l'AppImage et son fichier `.sha256` dans le même dossier, puis vérifiez la somme depuis ce dossier :

```bash
sha256sum -c LetsGoRecomp-<version>-linux-x86_64.AppImage.sha256
```

Pour l'archive, utilisez `sha256sum -c LetsGoRecomp-<version>-linux-x86_64.tar.gz.sha256`. Ne lancez pas le programme si la vérification échoue.

La release fournit également `BUILD-INFO.txt`, `DEPENDENCIES.json` (versions, commits et sommes attendues des dépendances), `build-manifest.json`, `build-manifest-release.json`, `build-size-report.txt`, `sbom.cdx.json` et `linux-elf-audit.json`. Le manifeste de release contient les sommes SHA-256 des fichiers téléchargeables ; le manifeste interne inventorie les fichiers de l'AppDir assemblé avant l'ajout final des dépendances par linuxdeploy. Le rapport ELF, lui, inspecte les ELF présents dans l'AppImage extrait.

## Installer et préparer le jeu

1. Téléchargez l'AppImage ou l'archive depuis la page Releases.
2. Lancez l'application et ouvrez l'onglet **Game**.
3. Choisissez le dossier contenant les dossiers `exefs/` et `romfs/` de votre propre copie du jeu déjà extraite. Les fichiers `.xci`/`.nsp` doivent être extraits au préalable.
4. Le premier setup prépare les fichiers, construit ou copie l'image RomFS puis recompile le code. Cette opération peut prendre plusieurs minutes ; elle est normalement nécessaire une seule fois pour une même configuration.

Aucun fichier de jeu, clé, sauvegarde ou dump n'est fourni par le projet. Choisissez uniquement du contenu auquel vous êtes légalement autorisé à accéder.

Avant le setup graphique, vous pouvez vérifier un dossier sans modifier de fichiers ni lancer le générateur ou le compilateur. Pour une vérification directe, la ligne de commande ci-dessous est préférée. Pour vérifier dans le launcher, définissez `LARECOMP_SETUP_DRY_RUN=1`, sélectionnez le dossier du jeu puis lancez le setup : le launcher affiche le résultat au lieu de préparer le jeu. `LARECOMP_SETUP_REDACT_PATHS=1` masque les chemins personnels. Il n’existe pas de variable `LARECOMP_SETUP_DIR` ; le dossier doit être choisi dans l’interface :

```bash
./LetsGoRecomp-<version>-linux-x86_64.AppImage --setup-dry-run "/chemin/vers/le/dossier"
```

Pour un rapport qui n'affiche pas les chemins locaux, ajoutez `--redact-paths` :

```bash
./LetsGoRecomp-<version>-linux-x86_64.AppImage --setup-dry-run "/chemin/vers/le/dossier" --redact-paths
```

Codes de sortie du diagnostic : `0` dossier reconnu et valide ; `2` dossier invalide ou incompatible ; `3` fichier de jeu empaqueté à extraire ; `4` accès refusé ; `64` arguments invalides.

## Emplacement des données

En mode AppImage, les ressources applicatives sont lues depuis le bundle et les données variables sont écrites hors du bundle en lecture seule :

- avec `XDG_DATA_HOME` absolu défini : `$XDG_DATA_HOME/lasrecomp/` ;
- sinon : `~/.local/share/lasrecomp/`.

Le dossier contient les fichiers du jeu préparés sous `extracted/`, la configuration `larecomp.ini`, les sauvegardes, les mods, les caches de shaders/pipelines, les polices facultatives et le journal `lasrecomp.log`. Le journal précédent peut être conservé sous `lasrecomp-prev.log` pour faciliter le diagnostic. Le paramètre `LARECOMP_DATA_ROOT` permet aux environnements de test de choisir un dossier de données explicite ; utilisez-le uniquement lorsque vous comprenez bien où l'application écrira.

## Diagnostic et rapport de bug

Pour un problème de lancement, de rendu ou de setup, joignez autant que possible :

1. `lasrecomp.log` et `lasrecomp-prev.log` s'ils existent ;
2. nom et version de la distribution Linux, sortie de `ldd --version`, architecture CPU ;
3. modèle GPU, version du pilote et sortie de `vulkaninfo --summary` (si `vulkaninfo` est installé) ;
4. modèle d'AppImage/ archive utilisé, résultat de `sha256sum -c`, et la phase de setup en échec.

Ne publiez pas de dumps du jeu, de clés, de sauvegardes ou de contenu propriétaire dans une issue.

## État de validation

La CI exécute le runtime avec `--version`, teste le helper `lasgen` empaqueté, exécute le diagnostic setup sur des fixtures synthétiques, extrait l'AppImage, contrôle les dépendances ELF et lance `--self-test` sans fichier du jeu. Les runs réels de génération/compilation avec un dump, l'expérience de jeu bout en bout et la couverture de l'ensemble des pilotes Vulkan restent à valider séparément ; ne considérez pas ces contrôles CI comme une certification du gameplay.
