# Plan d'optimisation — AppImage, CI et distribution Linux

- **Dépôt :** [rakmahefa/letsgo-recomp](https://github.com/rakmahefa/letsgo-recomp)
- **Base analysée :** `main`, commit `bdde3ad1036e47bcb109b47ff887cef512690059` (2026-10-26)
- **Objectif :** rendre la distribution Linux plus fiable, vérifiable, reproductible et simple à maintenir avant d'investir dans des optimisations agressives de taille ou de temps de compilation.
- **Périmètre produit immédiat :** AppImage et archive autonome Linux **x86_64**. ARM64 reste une cible distincte à valider, pas une promesse de distribution.

## 1. Priorités

| Priorité | Travail | Pourquoi | Livrable |
|---|---|---|---|
| **P0 — release integrity** | Lier le tag au SHA du build, valider la version et empêcher les tags déjà existants | Éviter qu'une release annonce une version/commit différent du binaire livré | Workflow de publication durci + tests de validation |
| **P0 — dry-run de publication** | Faire passer les mêmes validations sans créer de tag, release ni asset | Tester le parcours réel avant une publication irréversible | Mode `dry_run` par défaut et résumé de prépublication |
| **P1 — latence et parallélisme du setup** | Mesurer la recherche, RomFS, génération/compilation et établir un budget global pour générateurs + compilateurs | Le premier setup est long ; les quatre générateurs ne sont pas comptés dans la limite `jobs` des compilateurs | Mode setup dry-run, timings, pic RSS et ordonnancement global validé par benchmark |
| **P1 — packaging correctness** | Vérifier les dépendances ELF de tous les exécutables livrés et tester le chemin AppImage | Le runtime principal n'est pas le seul programme exécuté : le générateur et Zig sont nécessaires au setup local | Smoke tests de bundle réutilisables |
| **P1 — supply chain** | Vérifier hashes/signatures, verrouiller les dépendances et réduire les actions non pinnées | Construire depuis des entrées explicites et auditables | Manifest de dépendances + hashes + pinning |
| **P1 — metadata/legal** | Aligner tag, version, notes, licence, checksum et SBOM | Rendre l'artefact identifiable et redistribuable dans de bonnes conditions | Manifeste de release et notices complètes |
| **P2 — CI time** | Mesurer puis mettre en cache téléchargements et compilations sûres | Éviter de rebâtir systématiquement les mêmes dépendances | Temps par étape publiés, caches à clé stricte |
| **P2 — test coverage** | Tester chemins XDG, ressource du binaire, helper, Zig et échec contrôlé | La compilation ne valide pas le premier démarrage d'un utilisateur | Tests automatiques indépendants des ROM |
| **P2 — utilisateur/docs** | README Linux, prérequis hôte et procédure de dépannage | L'utilisateur doit comprendre les limites avant téléchargement | Section Linux cohérente avec les artefacts |
| **P3 — taille/architecture** | Réduire Zig uniquement si mesuré, clarifier la cible ARM64 | Éviter une optimisation de taille qui casse la recompilation à la première exécution | Rapport de taille et décision documentée |

## 2. P0 — Version, tag et provenance des artefacts

### 2.1 Une seule source de version

Aujourd'hui, la version d'exécution est définie dans `runtime/paths.h` via `RT_APP_VERSION`; le build Linux construit les noms d'artefacts à partir de cette valeur alors que la publication accepte un tag manuel libre. Des releases visibles portent un tag `v0.6.x-linux` avec des fichiers `LetsGoRecomp-0.5.0-linux-x86_64.*`, tandis que la source analysée indique `0.7.5`.

**Spécification :**
1. La version source est lue depuis `RT_APP_VERSION` pendant le build.
2. L'artefact contient un fichier texte généré automatiquement, par exemple `BUILD-INFO.txt`, avec version, commit SHA, branche, architecture, date UTC du build et version du toolchain.
3. Le workflow de release télécharge uniquement les artefacts d'un run accepté.
4. Le tag et la version de bundle doivent suivre une convention définie : `v<version>-linux` pour les releases Linux, ou une autre convention unique documentée. Ne pas mélanger plusieurs règles.
5. En cas de mismatch, le workflow échoue **avant** création de la release.
6. Le SHA de source attaché au tag doit être le même que le `headSha` du run de build sélectionné.

### 2.2 Valider le run sélectionné

Dans `.github/workflows/publish-linux.yml`, valider explicitement, en plus de `status=completed`, `conclusion=success` et `workflowName=Linux native build` :

- le dépôt attendu ;
- les événements acceptés (par défaut, uniquement un `push` autorisé ; exclure les runs `pull_request` pour une release) ;
- la branche autorisée, par exemple `main` ou une branche de release explicitement permise ;
- le SHA de commit qui sera la cible du tag ;
- la version embarquée dans `BUILD-INFO.txt` et le nom de chaque artefact.

Créer le tag/release avec la cible de commit du run validé — ne pas dépendre de la tête actuelle de la branche par défaut. Enregistrer ce SHA dans les notes ou comme fichier joint.

### 2.3 Vérifier l'existence d'un tag séparément

Le test actuel basé sur `gh release view "$TAG"` protège contre une release déjà existante, mais ne démontre pas qu'un tag Git du même nom n'existe pas sans release. Ajouter un contrôle spécifique du ref Git. Ne poursuivre que si le ref est réellement absent ; ne pas traiter un échec réseau/API comme une preuve d'absence.

### 2.4 Réduire les permissions

Déplacer les permissions d'écriture de contenu au job `publish`, et garder le job de validation de syntaxe et les builds en lecture seule. Les événements PR ne devraient jamais avoir besoin du droit `contents: write`. Conserver `actions: read` uniquement là où il faut inspecter/télécharger un run.

**Critères d'acceptation :**
- Un tag déjà présent — même sans release associée — bloque le job.
- Un run PR, un run d'une branche non permise ou un run échoué bloque la publication.
- Un artefact 0.5.0 ne peut pas être publié sous un tag 0.6.1/0.7.5.
- Le tag pointe sur le SHA du run de build.
- Les checksums sont recalculés avant publication ; les assets sont publiés seulement si tous les contrôles passent.
- Les tests négatifs des versions et du tag sont automatisés avec des fixtures/mocks, sans publier réellement de release.

### 2.5 Dry-run de publication obligatoire

Ajouter une entrée booléenne **dry_run** au workflow publish-linux.yml ; elle doit être activée par défaut. Le mode dry-run suit les mêmes validations que la publication réelle, mais n'effectue aucune mutation GitHub.

Comportement attendu :

1. Valider le run_id, le nom du workflow, l'événement, la branche autorisée, le SHA du commit, la cohérence version/tag et la disponibilité des artefacts.
2. Télécharger les artefacts et recalculer les SHA-256 exactement comme le ferait la publication réelle.
3. Vérifier que le tag Git est absent. Un tag déjà présent ou une erreur API ambiguë bloque la prépublication ; un échec réseau ne doit jamais être interprété comme « tag absent ».
4. Si dry_run=true, ne pas appeler gh release create, ne pas créer de tag, ne pas téléverser d'asset et ne pas accorder de permissions d'écriture au job de validation. Écrire dans GITHUB_STEP_SUMMARY le SHA source, le tag proposé, la version détectée, les noms, tailles et checksums des fichiers qui seraient publiés.
5. N'autoriser la publication réelle que lorsque dry_run=false est explicitement choisi. Refaire les contrôles dans le même run et ne pas dépendre d'un résumé de dry-run ancien.
6. Ajouter des tests automatisés des cas acceptés et rejetés avec commandes GitHub mockées/fixtures ; au moins un test manuel workflow_dispatch avec dry_run=true doit vérifier le workflow contre un artefact réel sans publier quoi que ce soit.

Le dry-run n'est pas un raccourci qui saute les étapes risquées : il exécute les validations d'entrée, de version, de checksum et de provenance, puis s'arrête avant toute écriture. La procédure de publication doit distinguer clairement « prévalidation réussie » de « release publiée ».

Critères d'acceptation supplémentaires :
- Le mode par défaut ne peut créer aucune release, tag ou asset.
- Les logs et le résumé affichent explicitement **DRY RUN — aucune modification GitHub effectuée**.
- Un test automatisé prouve que la commande de création de release n'est jamais appelée en dry-run.
- Une vérification réelle ne peut pas réutiliser aveuglément le résultat d'un dry-run antérieur : les artefacts et checksums sont contrôlés à nouveau.

## 3. P1 — Packaging AppImage robuste

### 3.1 Contrat du bundle

Garder le format actuel avec `usr/bin/LetsGoRecomp`, `lasgen/`, `zig/`, `gamelib-src/`, un `AppRun`, l'entrée desktop, l'icône et les notices. Garder les données modifiables hors du bundle : `extracted/`, sauvegardes, mods, configuration et cache shader sont des données de l'utilisateur.

| Élément | Règle |
|---|---|
| Runtime principal | Dépendances nécessaires présentes ; aucune bibliothèque accidentellement résolue depuis le répertoire `build/` du runner. |
| Vulkan | Garder le chargeur/driver Vulkan et le pilote GPU comme prérequis système. Ne pas inclure un pilote du runner dans l'AppImage. |
| SDL et FFmpeg | Embarquer les versions attendues, et contrôler leurs SONAMEs ainsi que la résolution réelle des bibliothèques. FFmpeg doit rester la build LGPL-only configurée par le workflow. |
| `lasgen` | Vérifier l'exécutable PyInstaller, toutes les extensions natives Capstone/Unicorn et leurs dépendances dynamiques. |
| Zig | Vérifier le binaire, les headers et libc sources nécessaires à `zig cc` sur le système supporté ; ne pas supprimer de fichiers sans test de génération/link. |
| Ressources | Vérifier les fichiers `gamelib-src`, la police, les icônes et les licences présentes, avec une liste attendue versionnée. |
| Données utilisateur | Vérifier le répertoire XDG et la possibilité d'écrire en dehors du point de montage AppImage. |

### 3.2 Vérification ELF de tous les exécutables

Ajouter une étape unique après assemblage de l'AppDir :

1. Identifier chaque exécutable ELF et chaque extension native avec `file`/la signature ELF, sans traiter les fichiers de données comme des binaires.
2. Examiner la résolution dynamique avec `lddtree` ou un équivalent contrôlé pour :
   - `usr/bin/LetsGoRecomp` ;
   - `usr/bin/zig/zig` ;
   - `usr/bin/lasgen/lasgen` ;
   - les bibliothèques natives chargées par PyInstaller.
3. Faire échouer le build si une dépendance attendue comme embarquée est introuvable ou vient d'un chemin non autorisé.
4. Maintenir une allowlist documentée des bibliothèques hôte : Vulkan loader/driver, stack graphique et audio, libc/GLIBC et intégration desktop.
5. Archiver les rapports de dépendances comme artefacts CI de diagnostic.

Ne pas se limiter à grepper le texte `not found` d'un seul `ldd` ; un rapport structuré par fichier binaire est préférable.

### 3.3 Smoke tests AppImage

La vérification actuelle extrait l'AppImage et contrôle `AppRun` plus le binaire principal. Étendre-la en étapes distinctes :

- **structure** : extraction, fichiers requis, permissions exécutables, icône et fichier desktop valides ;
- **dépendances** : contrôle ELF complet de l'AppDir extrait ;
- **lanceur** : lancer le vrai AppImage avec `APPIMAGE_EXTRACT_AND_RUN=1` dans un runner ou conteneur de test ;
- **ressources** : confirmer que les ressources sont résolues depuis le bundle, et non depuis la racine source ;
- **données** : avec HOME/XDG temporaires, vérifier que logs/configuration sont créés à l'emplacement attendu ;
- **setup sans jeu** : confirmer que l'absence des données de jeu produit un message d'erreur contrôlé et n'écrit aucun fichier propriétaire.

Si une validation nécessite un serveur graphique ou un Vulkan ICD, l'installer explicitement dans l'environnement de test. Si elle ne peut pas être exécutée dans le runner, la déclarer « non validée » plutôt que présenter l'extraction comme un test de lancement.

Un mode `--version`/ `--self-test` sans jeu serait utile pour rendre les tests reproductibles et éviter d'automatiser des clics UI fragiles.

### 3.4 FUSE 2 / mode d'extraction

Le bundle annonce une solution de repli `APPIMAGE_EXTRACT_AND_RUN=1`. Tester ce mode dans la CI et documenter la commande exacte dans le README Linux. L'existence de ce fallback ne remplace pas les tests sur un système réel sans FUSE 2.

## 4. P1 — Chaîne d'approvisionnement et dépendances reproductibles

### 4.1 Créer une définition unique des dépendances

Garder les versions sources comme données explicites : LLVM/Clang, Vulkan-Headers, VMA, FFmpeg, shaderc + ses dépendances, SDL3, PyInstaller/Capstone/Unicorn/LZ4, Zig et linuxdeploy.

Pour chaque source, enregistrer :
- version/release ;
- URL de source ;
- SHA-256 d'archive ou commit Git complet ;
- licence ;
- méthode de build et options importantes ;
- libs incluses statiquement, dynamiquement ou chargées à l'exécution.

### 4.2 Vérifier chaque téléchargement

- Réutiliser le modèle de `tools/fetch_zig.sh`, qui vérifie déjà un SHA-256 attendu.
- Ajouter le SHA-256 attendu des archives FFmpeg et de linuxdeploy, et vérifier avant extraction/exécution.
- Pour les téléchargements VMA/header/license et autres fichiers raw, pinner le contenu par checksum.
- Remplacer l'exécution de `llvm.sh` non figé par une méthode documentée dont l'identité/version est verrouillée, ou pinner/vérifier son contenu et la version exacte de Clang installée.
- Préférer un commit explicite pour les clones de sources, même si l'URL utilise aussi un tag lisible.
- Pinner les GitHub Actions externes par SHA immuable et utiliser une politique automatisée de mise à jour des pins.
- Verrouiller le set Python, idéalement versions + hashes via un fichier de lock. Une simple mise à niveau de `pip` à la dernière version rend les environnements temporellement variables.

Ne pas confondre « même nom de version » avec « octets identiques » ; le contrôle doit échouer avant d'exécuter une archive qui n'a pas le hash attendu.

### 4.3 Manifeste de build et provenance

Générer un artefact `build-manifest.json` (ou JSON équivalent versionné) contenant :
- commit/source ref, version applicative et architecture ;
- versions exactes de chaque toolchain ;
- options FFmpeg, SDL, shaderc et compilation ;
- SHA-256 des artefacts ;
- rapport des dépendances ELF ;
- liste et version des composants livrés.

Ajouter une attestation de provenance de l'artefact lorsque la configuration GitHub le permet. La provenance doit se rattacher au commit sélectionné et au run de build, pas simplement au nom du fichier.

## 5. P1 — Licences et SBOM

Le workflow copie déjà plusieurs licences de bibliothèques importantes. Formaliser le reste avant d'augmenter l'audience des releases.

### Travail demandé

1. Définir un tableau source « composant, version, type de liaison, binaire inclus, licence/notice, chemin dans l'artefact ».
2. Inclure les notices pertinentes pour le runtime et pour le helper PyInstaller (notamment les composants Capstone/Unicorn effectivement distribués).
3. Inclure les avis de licence de Dear ImGui, SMAA, stb, bcdec, Baloo 2/OFL, FidelityFX et autres fichiers réellement embarqués, selon leurs licences et le mode de distribution.
4. Garder FFmpeg en build LGPL-only et vérifier que les options configurées concordent avec les bibliothèques produites.
5. Générer un SBOM SPDX ou CycloneDX dans la CI et le publier avec les assets.
6. Ajouter un test qui échoue lorsqu'un binaire/librairie livré ne se rattache à aucune entrée de manifeste ou lorsqu'une notice requise manque.

Le SBOM doit refléter le résultat final assemblé (y compris les binaires fournis par PyInstaller), pas uniquement la liste des paquets installés dans Ubuntu.

## 6. P2 — Optimiser le temps de CI sans perdre en fiabilité

### 6.1 Mesurer avant de mettre en cache

Le workflow courant reconstruit FFmpeg, shaderc et SDL3 et installe plusieurs toolchains à chaque exécution. Ajouter un résumé des durées par étape et enregistrer le temps total de build avant d'activer des caches.

### 6.2 Caches proposés

| Cache | Clé conseillée | Règle d'invalidation |
|---|---|---|
| Archives sources validées (FFmpeg, Zig, linuxdeploy, etc.) | OS + architecture + version + SHA-256 attendu | Nouveau hash/version |
| Pip / wheel cache | OS + Python + hash du lock | Tout changement du lock |
| `ccache` pour C/C++ | OS + version exacte de Clang + options + hash dépendances | Toolchain, flags ou headers source changés |
| Artefacts compilés SDL/shaderc/FFmpeg | OS + architecture + compiler ID + versions/options | Invalider dès qu'une dépendance ou option de configuration change |
| PyInstaller | Lock Python + version de PyInstaller + hash du spec et des scripts | Lock/spec/scripts changés |

Utiliser une action de cache elle-même pinnée. Éviter de mettre en cache l'intégralité de `build/` sous une clé trop large : un objet compilé avec un ancien header ou un mauvais flag peut produire une panne difficile à diagnostiquer. Il faut conserver le test de dépendances et le smoke test après cache.

### 6.3 Parallélisme

Le `make -j2` du workflow est conservateur. Ne l'augmenter qu'après mesure de la mémoire maximale des étapes FFmpeg/shaderc et du runtime. Si la compilation est limitée par mémoire, rendre le nombre de jobs explicite (par exemple une variable CI) et garder une limite sûre par défaut. Ne pas optimiser au détriment de la reproductibilité.

### 6.4 Séparer validation rapide et packaging complet

Créer au besoin deux chemins :
- **validation rapide PR** : format/validation YAML, compilation runtime sur les sources pertinentes, tests de scripts et headers, tests unitaires sans dépendance aux dumps ;
- **bundle complet** : toolchain complète, AppDir/AppImage, checksums, rapport ELF, SBOM, artefacts téléchargeables.

Le packaging complet doit continuer d'être exécuté au moins sur les changements runtime, Makefile, scripts de génération, dépendances et workflows. Ne pas ignorer un changement de `tools/` ou `third_party/` qui affecte l'artefact.

## 7. P2 — Couverture de tests sans données du jeu

L'absence de ROM dans la CI est intentionnelle : le dépôt et les artefacts ne doivent pas inclure de données propriétaires. Les tests ci-dessous ne nécessitent aucun dump.

| Test | Cible | Résultat attendu |
|---|---|---|
| Version et métadonnées | `runtime/paths.h`, workflow | La version du bundle, BUILD-INFO et le nom des artefacts sont identiques. |
| Contrat AppDir | `build-linux.yml` | Tous les chemins requis existent ; aucun dossier `extracted/`, `generated/`, save ou mod n'est inclus. |
| ELF / SONAME | AppDir extrait | Aucune dépendance embarquée manquante ; hôte autorisé clairement déclaré. |
| AppRun | `AppRun`, wrapper et AppImage | Le runtime est lancé depuis les chemins embarqués, sans dépendre du checkout ou du CWD. |
| XDG / données | `runtime/paths.c`, `runtime/platform/linux.c` | `XDG_DATA_HOME` absolu est respecté ; XDG relatif est ignoré ; HOME manquant et dossier non inscriptible produisent un résultat contrôlé. |
| Ressources | `runtime/paths.c`, `runtime/gamebuild.c` | `lasgen`, Zig et `gamelib-src` sont découverts depuis le package. |
| Helper | `tools/lasgen.spec` | Le générateur démarre et affiche l'aide/usage sans dépendre d'un Python du système ; vérifier les bibliothèques Capstone/Unicorn. |
| Zig | `tools/fetch_zig.sh` | Binaire et données de compilation présents, hash vérifié, commande compiler/link de probe fonctionnelle. |
| Échec contrôlé | Runtime sans données de jeu | Message clair, pas de crash obscur ni de fichiers de jeu/sauvegarde créés. |
| Checksums | Artefacts finaux | Les deux SHA-256 se vérifient depuis les fichiers téléchargés. |
| Dry-run publication | publish-linux.yml | Tous les contrôles s'exécutent, un résumé est produit, aucune release/tag/asset n'est créé. |
| Dry-run setup | gamesetup.c, découverte des fichiers | Source classée, aucun fichier modifié, aucun générateur ni compilateur lancé. |
| Licences / SBOM | Artefacts finaux | Chaque composant livré est documenté et possède sa notice requise. |

Ajouter ensuite une grille manuelle de validation gameplay Linux, distincte de la CI automatisée : Eevee/Pikachu, scènes de départ, save/load, audio, contrôleurs, transitions et GPU Vulkan. Le statut de cette grille doit figurer dans la documentation (non testé, partiellement testé, validé), sans déclarer un support de bout en bout sur la seule base de la compilation CI.

## 8. P1 — Préparation initiale du jeu : investigation prioritaire et corrections

### 8.1 Résultat de la vérification statique

La chaîne de setup a été suivie dans runtime/ui/launcher_lg.mm, runtime/gamesetup.c, runtime/romfs_build.c et runtime/gamebuild.c. Le dépôt ne contient pas les fichiers de jeu de l'utilisateur, et aucun benchmark sur sa machine n'a été exécuté ici : les points ci-dessous sont des causes potentielles confirmées par le code, mais la phase dominante chez l'utilisateur reste à mesurer.

| Phase | Ce que le code fait actuellement | Diagnostic |
|---|---|---|
| Recherche après sélection | find_game() parcourt récursivement les dossiers jusqu'à la profondeur 5, dans l'ordre de readdir(). Il identifie romfs/ via bin/message, mais si exefs n'a pas encore été trouvé, il continue à parcourir les sous-dossiers du RomFS, sauf le dossier nommé bin. | Cause évitable confirmée par lecture du code. Un grand RomFS peut être scanné inutilement avant que le dossier ExeFS soit trouvé. |
| Copie d'ExeFS / image existante | romfs_copy_tree() tente de créer des hard links ; en cas d'échec (par exemple systèmes de fichiers différents), il copie les fichiers avec des E/S classiques. Pour un romfs.bin existant, le fast path est le hard link ; le fallback copie tous les octets avec un buffer de 1 Mio. | Le temps dépend du type d'entrée et du fait que la source et la destination partagent le même système de fichiers. |
| Construction depuis romfs/ | romfs_build() scanne l'arbre, fait un stat() sur les entrées, construit les tables et trie les fichiers/répertoires, puis lit et réécrit séquentiellement toutes les données dans romfs.bin avec un buffer de 4 Mio. | Cette écriture complète est attendue avec le format actuel, mais elle peut être limitée par les métadonnées, la lecture de petits fichiers ou les E/S du volume. Aucun temps de scan séparé n'est exposé. |
| Génération et compilation du code du jeu | L'AppImage est câblée pour lancer le générateur livré dans `usr/bin/lasgen/lasgen` et Zig dans `usr/bin/zig/zig`. `gamebuild_run()` lance quatre processus `lasgen` (main, sdk, subsdk0, subsdk1) puis compile en parallèle les chunks C via plusieurs processus `zig cc`. `tools/gen.py` ne contient pas de pool de threads interne : chaque processus traite son module de manière essentiellement séquentielle. | Le parallélisme existe, mais le budget `jobs` ne compte que les compilateurs : jusqu'à quatre générateurs supplémentaires s'exécutent en même temps. Risque de concurrence CPU/RAM excessive à mesurer. Pas de cache d'objets conservé entre les builds. Le README indique environ 22 minutes sur une machine à 20 threads ; c'est un repère, pas un benchmark de la machine concernée. |
| Barre de progression | gamesetup.c attribue 15 % à la copie/image et 85 % au code du jeu. La recherche des fichiers et le scan initial RomFS n'émettent pas un progrès en octets. | Le launcher peut paraître figé pendant une recherche/scan long, et les pourcentages ne représentent pas nécessairement le temps restant. |

**Conclusion de l'investigation :** il est justifié de donner à ce sujet une priorité P1. La première correction ciblée est de supprimer la descente dans l'arbre d'un RomFS déjà reconnu pendant la recherche d'ExeFS. En parallèle, il faut mesurer séparément le scan, la création de romfs.bin et le générateur/compilateur, puis ne faire les optimisations I/O ou de compilation qu'en fonction des résultats. Il ne faut pas annoncer un gain chiffré avant un benchmark comparable.

### 8.2 Vérification du parallélisme et du générateur livré dans l'AppImage

**Verdict de revue statique : oui, le chemin normal de l'AppImage utilise plusieurs processus de travail en parallèle.** Ce n'est pas simplement une barre de progression sur un seul thread. En revanche, le générateur Python n'a pas son propre pool de threads : le parallélisme vient surtout de plusieurs processus `lasgen` et des invocations `zig cc`.

#### Chemin exact d'exécution

1. `runtime/gamesetup.c:setup_start()` crée un thread pthread détaché pour le setup afin de ne pas bloquer la boucle UI. Ce thread effectue la recherche, la copie et la préparation RomFS, puis appelle `build_code()`.
2. `build_code()` calcule le nombre de jobs à partir de `SDL_GetNumLogicalCPUCores()` et `SDL_GetSystemRAM()`.
3. En mode AppImage normal, `runtime/gamebuild.c:find_tools()` recherche le générateur à côté du runtime sous `usr/bin/lasgen/lasgen` et Zig sous `usr/bin/zig/zig`. Le workflow Linux construit le générateur avec PyInstaller en mode **onedir**, puis copie les répertoires `lasgen/` et `zig/` dans l'AppDir. Python ou Clang système n'est donc pas requis pour ce chemin normal. `LARECOMP_GEN` et `LARECOMP_CC` peuvent toutefois remplacer ces outils si l'utilisateur les définit.
4. `gamebuild_run()` lance quatre processus générateur via `plat_spawn()` ; sur Linux, `runtime/platform/linux.c` utilise `posix_spawn()`. Les quatre modules sont traités simultanément : `main`, `sdk`, `subsdk0` et `subsdk1`.
5. `tools/gen.py` lit chaque NSO, décompresse son image, découvre les frontières de fonctions, parcourt les instructions, résout les cibles de branches/jump tables, puis écrit le C en chunks. Le code de génération utilise `unicorn` et `capstone`, mais ne crée pas de pool de threads ou de processus à lui seul : un processus `lasgen` traite un module.
6. À mesure que chaque chunk C devient disponible, `gamebuild_run()` lance des processus de compilation indépendants `zig cc -c` jusqu'à remplir les créneaux de compilation autorisés. La génération et la compilation se chevauchent. L'édition de liens finale est une seule tâche.

Le packaging du générateur est cohérent avec ce chemin : `tools/lasgen.spec` inclut les imports Python du générateur, collecte les bibliothèques natives de Capstone/Unicorn et ajoute explicitement la bibliothèque Unicorn versionnée. Le workflow Linux vérifie actuellement que `build/helper/lasgen/lasgen` existe et est exécutable, mais ce test ne suffit pas à prouver que l'exécutable démarre et charge toutes ses bibliothèques natives ; il n'y a pas encore de test de traduction réelle dans la CI.

#### Limite actuelle du budget de parallélisme — risque concret à vérifier

Le code fait l'équivalent de :

`ram_gb = SDL_GetSystemRAM() / 1024`

`jobs = max(1, min(logical_cores, ram_gb - 2))`

SDL documente que `SDL_GetSystemRAM()` renvoie la RAM totale configurée en MiB, et que `SDL_GetNumLogicalCPUCores()` renvoie le nombre de processeurs logiques ([RAM](https://wiki.libsdl.org/SDL3/SDL_GetSystemRAM), [CPU](https://wiki.libsdl.org/SDL3/SDL_GetNumLogicalCPUCores)). `gamebuild_run()` plafonne ensuite `jobs` à 64, mais ce nombre désigne **uniquement les processus de compilation**.

Comme les quatre générateurs sont démarrés indépendamment et ne sont pas déduits du budget `jobs`, la charge peut atteindre approximativement `4 générateurs + jobs compilateurs` processus enfants actifs, sans compter le runtime et le linker ponctuel. Exemple : sur une machine signalant 12 CPU logiques et 16 GiB de RAM, la formule autorise 12 compilateurs ; les quatre générateurs peuvent s'ajouter pendant la phase de chevauchement. Ce n'est pas une preuve de lenteur ou de panne, mais c'est un risque de surabonnement CPU/RAM.

Autre limite : la RAM totale et le nombre de CPU logiques ne représentent pas forcément la mémoire libre ni les quotas CPU/mémoire d'un conteneur/cgroup. Le calcul réserve 2 GiB de manière fixe, sans mesurer le pic mémoire actuel des processus. Or chaque générateur garde son propre état Python et manipule plusieurs représentations en mémoire du module (NSO/image décompressée, bytes de texte, tuple de mots, structures de découverte). Le pic RSS des quatre générateurs est donc à mesurer, pas à inférer à partir de la taille compressée des fichiers.

#### Corrections demandées

- Ajouter dans `lasrecomp.log` un résumé indiquant le chemin réellement choisi pour `lasgen` et Zig, le nombre de CPU logiques, la RAM totale détectée, la limite mémoire/CPU effective si disponible, le nombre de jobs compilateur et le nombre de générateurs actifs.
- Définir un **budget global de travail**, tenant compte des générateurs ET des compilateurs, plutôt que de limiter les seuls compilateurs. Mesurer d'abord le temps total, le débit par phase et le pic RSS ; ensuite comparer plusieurs budgets sur la même machine et les mêmes fichiers.
- Respecter les quotas cgroup/v2 et cpuset si l'application est utilisée dans un environnement restreint ; prévoir un réglage utilisateur explicite de jobs borné par la capacité détectée, avec une valeur par défaut prudente.
- Tester si lancer les quatre générateurs simultanément est optimal sur les machines à faible RAM. Possibilité à benchmarker : limiter le nombre de générateurs actifs et conserver le chevauchement génération/compilation.
- Vérifier le mode PyInstaller emballé par smoke test : démarrage du helper et `--help`, chargement des dépendances natives, puis un test de traduction sur un **NSO synthétique de test** si un fixture minimal fiable est disponible. Ne jamais introduire les fichiers du jeu de l'utilisateur dans la CI.
- Dans le log permanent, conserver un résumé concis par module avec durée et nombre de fonctions/chunks. Les logs détaillés actuels sont écrits dans `extracted/.gamebuild/gen_*.log` et le répertoire temporaire est supprimé après le build ; sans recopier leurs résumés dans `lasrecomp.log`, les données détaillées disparaissent.
- Ne pas considérer `lasgen --help` seul comme preuve qu'une traduction complète fonctionne : il ne valide que le démarrage de l'exécutable, tandis que le fixture doit valider le chargement de Unicorn/Capstone et le chemin de génération.

### 8.3 Ajouter une instrumentation de performance avant d'optimiser

Ajouter des mesures monotones dans runtime/gamesetup.c, runtime/romfs_build.c et runtime/gamebuild.c. N'émettre qu'un résumé par phase, pas une ligne par fichier.

Données à journaliser dans lasrecomp.log :

- find_game_ms : temps de recherche et profondeur/dossiers parcourus ;
- type de source : paire ExeFS + dossier RomFS, image romfs.bin existante, ou dump plat ; nombre de fichiers et octets estimés uniquement si ce comptage a été effectué ;
- temps de nettoyage ; copie d'ExeFS en distinguant hard link et copie réelle ; volume source/destination identique ou différent si disponible ;
- scan RomFS (durée, nombre de dossiers/fichiers, octets) ; assemblage des tables ; écriture de l'image (octets, durée, MiB/s) ; validation de l'image ;
- par module main/sdk/subsdk0/subsdk1 : durée de génération, nombre de fonctions/chunks, octets C ; compilation (durée, nombre d'objets/octet C) ; édition de liens et finalisation ;
- total setup, CPU logique, RAM détectée, nombre de jobs choisi et espace libre avant l'opération.

Utiliser la même horloge monotone que plat_now_ns(). Ne pas lire tous les octets uniquement pour produire des statistiques : les mesures de taille doivent provenir du scan normal, sinon les diagnostics allongeraient eux-mêmes l'installation.

Établir une baseline avec la même version, les mêmes fichiers et la même machine : exécution froide puis répétée, SSD/HDD si cela reflète les environnements visés, source sur le même volume et source sur un volume différent. Publier le temps de chaque phase et le temps total ; c'est le critère de décision, pas la seule barre de progression.

### 8.4 Introduire un setup dry-run non destructif

Prévoir un mode de diagnostic activable par un flag développeur (par exemple LARECOMP_SETUP_DRY_RUN=1 ou une commande --setup-dry-run <dossier>) qui suit la découverte et la validation de la source mais ne modifie rien.

Le dry-run doit :

- afficher le type et les chemins de source détectés (avec une option permettant de masquer les chemins personnels), la version/identité du jeu déterminable à partir des métadonnées et les actions prévues ;
- terminer après la validation et ne pas supprimer extracted/, ne pas créer ou remplacer romfs.bin, ne pas lancer les générateurs ni le compilateur ;
- ne pas calculer un hash complet du RomFS par défaut et ne pas faire un inventaire récursif coûteux dans le seul but d'afficher une estimation ; une option distincte --stats peut compter les fichiers/octet en chronométrant le scan ;
- retourner un code distinct pour « source valide », « dump non reconnu », « package .xci/.nsp à extraire » et « erreur d'accès », sans nécessiter de GPU ;
- afficher explicitement **DRY RUN — aucun fichier modifié, aucun processus de build lancé**.

Tests nécessaires avec de petits fixtures synthétiques, sans inclure de données propriétaires :

1. dossier exefs/ + romfs/ ;
2. dossier exefs/ + image romfs.bin ;
3. dump avec un ou plusieurs dossiers enveloppes ;
4. dump plat accepté par le setup ;
5. répertoire sans fichiers requis et dossier contenant uniquement un .xci/.nsp.

Avant/après le dry-run, vérifier que la liste et les SHA-256 des fichiers d'un répertoire temporaire n'ont pas changé, qu'aucune sortie extracted/ n'a été remplacée et qu'aucun processus lasgen/zig/compilateur n'a été lancé. Le mode --stats est optionnel, car son scan de comptage peut lui-même prendre du temps.

### 8.5 Corrections à réaliser dans l'ordre des mesures

**Correction 1 — réduire la recherche récursive (première correction ciblée).**

Réorganiser find_game() pour privilégier les layouts conventionnels (exefs/, romfs/ ou romfs.bin) depuis le dossier choisi et quelques dossiers enveloppes. Quand un répertoire est reconnu comme racine RomFS, ne pas y rechercher main.npdm et ne pas explorer ses arbres de ressources ; continuer uniquement dans les enveloppes/candidats possibles. Arrêter immédiatement les explorations inutiles lorsque les deux composantes sont trouvées. Conserver le support des dumps imbriqués et des dumps plats, et tester les layouts avec un ordre de dossiers différent. C'est une correction issue directement du code observé, à effectuer avant une refonte de la copie.

**Correction 2 — rendre la progression fidèle au travail réalisé.**

Remplacer la répartition rigide 15 %/85 % par des états/étapes distincts (recherche, préparation ExeFS, scan RomFS, écriture image, génération, compilation, linkage). Pendant une phase non mesurable, afficher son nom et un indicateur d'activité plutôt qu'un faux pourcentage. Lorsqu'un débit mesuré est disponible, afficher une quantité traitée et éventuellement MiB/s ; n'afficher un ETA qu'après suffisamment d'échantillons et en le présentant comme estimation. Le ressenti de lenteur doit être traité séparément du temps réel du travail.

**Correction 3 — traiter la construction de RomFS seulement si le profil l'identifie comme dominante.**

Si le scan des métadonnées est dominant, réutiliser les métadonnées collectées au lieu de faire un nouveau parcours et améliorer les structures de données/allocations avant de considérer du parallélisme. Si l'écriture est dominante, tester une préallocation de la taille finale connue et des chemins d'E/S adaptés à Linux ; comparer le débit et la robustesse sur des systèmes de fichiers pris en charge. Pour une image romfs.bin déjà fournie, mesurer les cas hard link et copie cross-device ; évaluer un clone copy-on-write (FICLONE quand pris en charge) avant le fallback de copie pour éviter un transfert intégral sur les volumes compatibles. Garder la copie classique comme fallback fiable. Ne pas paralléliser l'écriture de l'image avant d'avoir démontré un gain et validé les offsets, trous d'alignement et échecs disque.

**Correction 4 — réduire les compilations répétées du code du jeu.**

Mesurer génération et compilation séparément. Le premier build doit toujours produire les quatre modules à partir des fichiers de l'utilisateur ; ne pas promettre de le rendre instantané. Pour les changements d'application, de configuration CPU ou les setups répétés, étudier un cache local d'objets/générés indexé par une clé de contenu comprenant au minimum les hashes des NSO source, scripts du générateur, hle_symbols.txt, headers/ABI, options de compilation, niveau CPU et version de Zig/Clang. Écrire dans un répertoire temporaire puis publier atomiquement le résultat. Une entrée ne peut être réutilisée que si toute la clé correspond ; prévoir une limite de taille et une commande de purge. Le cache doit rester local, ne jamais être livré dans les releases et ne doit jamais stocker les données du jeu dans le dépôt.

**Correction 5 — prévol stockage et chemins cross-device.**

Avant une copie susceptible de transférer plusieurs gigaoctets, vérifier l'espace disponible, identifier le type de source et avertir si une image complète va être copiée/construite. Le message doit expliquer la raison et éviter de donner l'impression que l'application est bloquée. Ne pas changer la politique de stockage de l'utilisateur ou conserver une référence externe silencieusement : toute solution sans copie exigerait une décision d'architecture et un traitement des chemins/symlinks distinct.

### 8.6 Critères d'acceptation et priorité

- [ ] Une exécution dry-run ne supprime, ne copie et ne crée aucun fichier et ne lance aucun processus de génération/compilation.
- [ ] Les timings établissent le pourcentage réel du temps passé dans la recherche, la préparation RomFS, la génération et la compilation.
- [ ] Le log de la build réelle confirme les chemins AppImage du générateur et de Zig, la valeur effective de `jobs`, le nombre de générateurs actifs et la capacité CPU/RAM détectée.
- [ ] Le planificateur traite ensemble les quatre générateurs et les processus `zig cc` ; le pic RSS ne dépasse pas la limite de test définie et le temps est comparé à la version actuelle.
- [ ] La CI exécute le générateur PyInstaller emballé (pas seulement `test -x`) et teste au minimum son démarrage/dépendances natives ; un fixture NSO synthétique valide la génération si disponible.
- [ ] Les logs différencient une image RomFS construite, une image existante hard-linkée et une copie complète cross-device.
- [ ] Le détecteur ne descend plus dans les ressources d'un RomFS reconnu pour rechercher ExeFS ; les dumps imbriqués et plats restent reconnus.
- [ ] La barre de progression indique la phase effective et continue d'évoluer pendant les phases lentes.
- [ ] Chaque optimisation I/O ou de compilateur est comparée sur les mêmes données/machine avec le temps par phase, le temps total, la mémoire maximale et le résultat fonctionnel.
- [ ] Aucun dump du jeu n'est nécessaire à la CI : les fixtures sont synthétiques. Les mesures d'installation de taille réelle sont faites manuellement par l'utilisateur, sur ses propres fichiers, et le rapport ne contient pas de données propriétaires.

**Priorité d'exécution :** ajouter les timings et le dry-run d'abord, puis corriger immédiatement la recherche qui peut explorer le RomFS. Les optimisations d'I/O et le cache de compilation viennent après la mesure de la phase dominante ; ne pas introduire une complexité de cache ou une copie parallèle si le temps est en réalité consommé ailleurs.

## 9. P2 — Documentation utilisateur et support

Mettre à jour `README.md` ou ajouter un `docs/LINUX.md` et le relier depuis le README.

Le guide Linux doit donner :
- statut expérimental actuel et limites fonctionnelles connues ;
- architecture livrée : x86_64 pour la release actuelle ;
- exigences annoncées par le bundle : GLIBC ≥ 2.35, CPU compatible avec les niveaux générés (vérifier la détection v2/v3), Vulkan 1.3, driver GPU compatible ;
- FUSE 2 et commande de repli `APPIMAGE_EXTRACT_AND_RUN=1` ;
- différence entre dépendances embarquées (SDL3, FFmpeg selon le build) et stack hôte (Vulkan/driver, graphiques/audio) ;
- emplacement de la configuration, des saves, des mods, du cache shader et des logs ;
- procédure de collecte de `lasrecomp.log`, distro, GPU/driver et résultat du test Vulkan ;
- procédure SHA-256 de vérification des téléchargements ;
- clause claire : les données du jeu doivent provenir de l'utilisateur, aucune donnée du jeu n'est fournie.

Mettre à jour les commentaires du Makefile qui qualifient le build Linux d'inutilisé/non testé, mais ne pas laisser entendre que le gameplay Linux est validé avant qu'il ne le soit.

## 10. P3 — Taille du bundle et optimisations de la toolchain

Les releases actuelles visibles contiennent un AppImage d'environ **87,5 MB** et une archive tar.gz d'environ **96,4 MB**. Ce sont des points de référence historiques ; mesurer les artefacts du nouveau commit avant d'en tirer une conclusion sur une régression.

### 10.1 Profiling du contenu

À chaque build de référence, publier un tableau `du -sh` par sous-répertoire et les plus gros fichiers :
- `usr/bin/LetsGoRecomp` ;
- `usr/bin/lasgen` et ses bibliothèques ;
- `usr/bin/zig` ;
- bibliothèques SDL/FFmpeg ;
- polices et assets ;
- données non exécutables et licences.

L'optimisation doit commencer là où la taille est réellement concentrée. Ne pas réduire la qualité de compression ou la compatibilité host pour une petite économie théorique.

### 10.2 Zig

`tools/fetch_zig.sh` télécharge Zig et enlève déjà des parties de libc qui ne correspondent pas à la cible. `tools/zig_slim.sh` construit une toolchain Windows spécialisée ; ce script n'est pas réutilisable tel quel sous Linux.

Évaluer un équivalent Linux uniquement si le rapport montre que Zig domine le bundle. Toute version réduite doit démontrer, sur une machine propre avec caches Zig vides :
- compilation de la bibliothèque générée ;
- linkage du shared object ;
- support des flags CPU retenus ;
- absence de recherche de headers/libc dans le checkout ou dans les dossiers du runner ;
- comportement après mise à jour de Zig.

Ne pas retirer arbitrairement `lib/std`, les headers glibc/musl requis, les sources de compiler-rt ou les composants utilisés implicitement par `zig cc`.

### 10.3 Réduction du checkout tiers

`third_party/imgui/` contient les backends, exemples et projets upstream qui ne sont pas tous compilés par le Makefile actuel. Cela alourdit surtout le checkout, pas forcément l'AppImage. La suppression n'est pas une priorité de release ; envisager un sous-ensemble seulement avec une procédure de mise à jour upstream, une liste claire des fichiers utilisés et les notices de licence intactes.

## 11. Support architecture et compatibilité

- **Cible de livraison actuelle :** `linux-x86_64`, construite sur `ubuntu-22.04` pour conserver le baseline GLIBC documenté.
- **Tests de compatibilité :** au minimum Ubuntu 22.04 et une distribution plus récente ; ajouter d'autres environnements représentatifs si des problèmes de dépendances hôte sont remontés.
- **ARM64 :** ne publier que si un runner natif/cross validé compile les dépendances et le runtime, construit l'AppImage correspondante, vérifie les ELF et fait un test de démarrage. Les noms d'artefact et le manifest doivent inclure l'architecture.
- **Vulkan :** les runners de compilation n'attestent pas la compatibilité avec tous les GPU. Séparer CI build, test logiciel de démarrage et validation réelle GPU.
- **GLIBC :** ne relever le baseline du runner qu'avec une décision de support/documentation ; sinon tester que les binaires ne dépendent pas d'une GLIBC plus récente que le minimum annoncé.

## 12. Séquence d'implémentation

### Étape 0 — valider sans publication et mesurer le setup du jeu

- [x] Ajouter dry_run au workflow de publication, activé par défaut, avec prévalidation en lecture seule et job de publication distinct. Le mode sans mutation est aussi couvert par un test de politique ; [ ] exécuter manuellement workflow_dispatch sur un artefact réel.
- [x] Ajouter les tests dry-run automatisés sur des fixtures synthétiques et un helper/compilateur marqueurs qui prouvent qu'ils ne sont pas lancés ; [ ] exécuter le parcours manuel workflow_dispatch sur de vrais artefacts.
- [x] Implémenter le mode setup dry-run CLI et launcher, les codes de sortie distincts, la redaction des chemins et des fixtures avant/après avec SHA-256 ; la compilation/test du dernier commit reste à valider par CI.
- [x] Instrumenter les durées de recherche/copie/scan/écriture, génération par module, compilation et linkage ; [ ] collecter le baseline sur une machine et un dump réels (pas de données de jeu disponibles pour la CI).
- [x] Ajouter le log des chemins de génération/compilation, le budget global et le smoke test AppImage des outils embarqués ; confirmer les valeurs dans le journal d'un build AppImage final lorsque la CI est terminée.
- [x] Ajouter l'échantillonnage du nombre maximal de processus enfants et du RSS des enfants directs sous Linux (échantillon ~50 ms ; les processus descendants ne sont pas comptés). Le pic de mémoire et les performances doivent encore être mesurés sur une machine cible.
- [x] Ajouter un smoke test du `lasgen` empaqueté et de Zig sans données du jeu ; [ ] ajouter une fixture NSO synthétique pour couvrir réellement l'analyse/génération.
- [x] Définir un budget borné commun aux générateurs et compilateurs, limité par CPU/RAM/cgroup, avec possibilité de le réduire via `LARECOMP_BUILD_JOBS`. Les valeurs doivent être ajustées uniquement après les mesures réelles.
- [x] Corriger `find_game()` : dès qu'un RomFS est reconnu, ne pas parcourir son arbre de ressources, trier les candidats et arrêter la recherche dès que les composantes requises sont trouvées.

### Étape 1 — sécuriser la release
- [x] Ajouter `BUILD-INFO.txt`, la version du binaire, le manifeste de build et un manifeste de release avec SHA-256 des artefacts.
- [x] Implémenter et tester la politique de dry-run sans jeton de publication ; [ ] exécuter workflow_dispatch avec de vrais artefacts et vérifier visuellement le résumé avant toute publication réelle.
- [x] Valider automatiquement workflow, event `push`, branche `main`, dépôt source, SHA complet, ref, tag/version et noms exacts des artefacts ; ajouter des tests positifs/négatifs.
- [x] Le job de publication passe explicitement le SHA source validé à `gh release create --target`.
- [x] Refuser la publication si le tag Git ou la release existe déjà ; distinguer le HTTP 404 d'une erreur réseau/permissions.
- [x] `contents: write` uniquement dans le job `publish`; tous les jobs de prévalidation et les évènements PR sont en lecture seule.
- [x] Ajouter des tests positifs/négatifs pour tag, workflow/run, branche/dépôt/SHA, version et noms d'artefact.

### Étape 2 — rendre le bundle testable
- [x] Ajouter l'audit de tous les ELF de l'AppImage extrait, avec liste autorisée des dépendances hôte et vérification des SONAME FFmpeg requis ; résultat CI du dernier commit en attente.
- [x] Ajouter `--version` avant initialisation SDL et `--self-test` qui vérifie ressources et outils embarqués sans données du jeu.
- [x] Ajouter à la CI un lancement de l'AppImage avec `APPIMAGE_EXTRACT_AND_RUN=1`, `--version` et `--self-test`; résultat sur le dernier commit encore à confirmer.
- [x] Tester `lasgen --help` et `zig version` empaquetés sans charger de dump.
- [x] Ajouter une allowlist des bibliothèques Linux hôte ; toute dépendance non résolue ou non autorisée fait échouer l'audit.

### Étape 3 — verrouiller les entrées et notices
- [ ] Plusieurs binaires/archives ont un SHA-256 vérifié et plusieurs dépôts Git sont pinnés par commit ; [ ] compléter les hashes pour chaque dépendance transitive (notamment `git-sync-deps` de shaderc et dépendances d'OS).
- [x] Pinner les actions GitHub par SHA immuable et plusieurs commits de sources ; le fichier `tools/linux-dependencies.json` énumère les références.
- [x] Ajouter `tools/requirements-linux-generator.txt` avec des versions directes exactes ; [ ] produire un lock de toutes les dépendances transitives avec hashes pour installation reproductible.
- [x] Générer le manifeste de build avec inventaire SHA-256, provenance, lock de dépendances, SBOM CycloneDX et manifeste final des artefacts.
- [x] Stager les notices livrées et vérifier leur présence avant packaging ; l'audit complet des licences/composants du SBOM reste à réviser.

### Étape 4 — mesurer et accélérer
- [x] Enregistrer les durées des phases runtime et le temps total du job ; générer un rapport de taille du bundle et les 25 fichiers les plus volumineux.
- [ ] Activer pip cache, cache des archives vérifiées puis `ccache`.
- [ ] Comparer temps à cache chaud/froid.
- [ ] Augmenter le parallélisme seulement après mesure de la mémoire.
- [ ] Refaire les mêmes tests post-cache pour exclure une corruption incrémentale.

### Étape 5 — clarifier le support Linux
- [x] Documenter l'AppImage et l'archive tar.gz dans le README et `docs/LINUX.md`.
- [x] Documenter GLIBC/Vulkan, intégration graphique/audio hôte, FUSE 2 et le mode d'extraction de repli.
- [x] Mettre à jour les commentaires Makefile sur le statut expérimental Linux.
- [x] Documenter que le gameplay bout en bout et la compatibilité GPU réelle ne sont pas certifiés par les tests CI.
- [ ] Décider séparément si ARM64 devient une cible officielle.

## 13. Définition de terminé (DoD)

Une release Linux est prête lorsque :

1. un tag/version/commit cohérent est validé automatiquement ;
2. le workflow de publication passe en dry-run avec les mêmes validations et sans aucune mutation ;
3. le build et les dépendances de chaque binaire embarqué passent les contrôles ;
4. l'AppImage se structure et démarre dans le scénario de test déclaré ;
5. le helper et Zig sont vérifiés avec un cache de compilation propre ;
6. les sommes SHA-256, manifest de build, provenance et SBOM sont publiés ;
7. chaque composant distribué dispose de la notice requise ;
8. README et note de release décrivent les exigences réelles et les limites connues ;
9. aucun dump, clé, save ou contenu propriétaire du jeu ne se trouve dans les artefacts.

Le parcours de setup du jeu est également prêt lorsque son mode dry-run ne modifie aucun fichier, que les durées des phases sont mesurables et que la recherche des fichiers ne parcourt plus inutilement les ressources d'un RomFS déjà reconnu.

**Ordre conseillé :** sécuriser et éprouver la release en dry-run, mesurer le setup initial, corriger la recherche excessive dans RomFS, puis traiter la phase dominante identifiée par les mesures. L'optimisation des temps et de la taille vient après la fiabilité et la mesure reproductible.
