# Audit des fichiers — Let's Go Recomp

- **Date de l'audit :** 2026-10-26
- **Dépôt :** [rakmahefa/letsgo-recomp](https://github.com/rakmahefa/letsgo-recomp)
- **Branche / commit observés :** \`main\` / \`bdde3ad1036e47bcb109b47ff887cef512690059\`
- **Statut CI observé :** le workflow [Linux native build, run 40262242512](https://github.com/rakmahefa/letsgo-recomp/actions/runs/40262242512) est terminé avec succès.
- **Portée :** inventaire des 458 fichiers suivis et revue statique ciblée des chemins critiques de build Linux, de l'AppImage, de la publication de release, de la gestion des ressources et du générateur livré. Les 260 fichiers sous \`third_party/\` sont inventoriés par composant ; ils n'ont pas tous été audités ligne par ligne comme du code propriétaire. Aucun binaire n'a été exécuté dans un environnement Linux de bureau par cette revue et aucun dump du jeu n'a été utilisé.

## 1. Résumé exécutif

La base comporte un runtime C/C++, un générateur ARM64→C, un Makefile multi-plateforme, un workflow Linux et un workflow de publication séparé. Le pipeline Linux produit un AppImage x86_64 et une archive autonome ; il embarque SDL3, FFmpeg LGPL-only et un compilateur Zig pour la compilation locale du code du jeu. Le répertoire utilisateur est séparé du runtime en lecture seule de l'AppImage.

La construction CI actuelle réussit, et le workflow de publication vérifie déjà le statut du build ainsi que les sommes SHA-256 des quatre artefacts attendus. Les risques prioritaires concernent surtout **la provenance des artefacts et les validations de packaging**, pas une panne de compilation constatée.

| ID | Priorité | Constat | État |
|---|---|---|---|
| A-01 | **P1** | Le tag de release n'est pas lié explicitement au SHA du build utilisé. | Risque de provenance confirmé dans le workflow |
| A-02 | **P1** | Versions divergentes entre tags de releases, noms d'artefacts historiques et version source actuelle. | Incohérence observable |
| A-03 | **P1** | Les contrôles AppImage ne valident pas les dépendances ELF de tous les exécutables livrés, ni un démarrage réel de l'AppImage. | Lacune de test |
| A-04 | **P1** | Plusieurs dépendances de build exécutables sont téléchargées sans vérification cryptographique explicite. | Risque de chaîne d'approvisionnement |
| A-05 | **P2** | La CI compile les grandes dépendances depuis zéro à chaque run et ne verrouille pas les paquets Python. | Optimisation et reproductibilité |
| A-06 | **P2** | La liste de licences distribuées ne couvre pas explicitement tous les composants embarqués. | Vérification et correction requises |
| A-07 | **P2** | Le README et le commentaire initial du Makefile restent centrés sur Windows malgré le pipeline Linux. | Documentation incomplète |
| A-08 | **P2** | La CI valide principalement la compilation et la structure du bundle, pas les parcours de lancement, de génération locale ou de régression. | Couverture limitée |
| A-09 | **P3** | La découverte de la racine de données et la destination du log sont codées à deux endroits. | Risque de dérive à long terme |
| A-10 | **P3** | Le dépôt vend une distribution x86_64 alors que certains éléments du Makefile décrivent des builds Linux multi-architecture. | Contrat de plateforme à clarifier |

## 2. Constats détaillés

### A-01 — Le workflow de publication ne lie pas le tag au commit du build (**P1**)

**Fichiers :** [\`.github/workflows/publish-linux.yml\`](.github/workflows/publish-linux.yml)

Le workflow valide qu'un \`run_id\` numérique correspond à un run terminé avec succès dont le nom est \`Linux native build\`, puis télécharge ses artefacts. La commande de création de release lance toutefois \`gh release create "$TAG"\` sans cible de commit explicite. Le workflow ne valide pas non plus que le run provient d'un push de la branche attendue, ni qu'il correspond au commit auquel le tag devrait pointer.

**Impact :** le binaire téléchargé peut provenir d'un commit différent de celui associé au tag de release. La somme SHA-256 prouve l'intégrité du fichier par rapport au checksum fourni, mais pas que ce fichier correspond au commit annoncé.

**Correction :** récupérer \`headSha\`, \`headBranch\` et \`event\` du run via \`gh run view\`, limiter les événements acceptés à une politique documentée (par exemple un push de \`main\)), puis créer la release avec \`--target <headSha>\`. Refuser un run PR ou un run d'une autre branche sauf exception explicitement approuvée. Enregistrer le SHA utilisé dans les notes de release et produire une attestation de provenance.

### A-02 — Version source, tags et noms d'artefacts ne sont pas alignés (**P1**)

**Fichiers :** [\`runtime/paths.h\`](runtime/paths.h), [\`.github/workflows/build-linux.yml\`](.github/workflows/build-linux.yml), [\`.github/workflows/publish-linux.yml\`](.github/workflows/publish-linux.yml)

La version source observée dans \`RT_APP_VERSION\` est **0.7.5**. Les releases visibles [\`v0.6.1-linux\`](https://github.com/rakmahefa/letsgo-recomp/releases/tag/v0.6.1-linux) et [\`v0.6.0-linux\`](https://github.com/rakmahefa/letsgo-recomp/releases/tag/v0.6.0-linux) contiennent des artefacts nommés **\`LetsGoRecomp-0.5.0-linux-x86_64.*\`**. Le workflow accepte un tag saisi manuellement et ne compare pas le tag à la version intégrée dans le bundle.

**Impact :** les utilisateurs et les scripts de téléchargement ne peuvent pas déduire de manière fiable la version réelle du binaire à partir du tag de release.

**Correction :** choisir une source de vérité unique. À la publication, extraire la version depuis l'artefact validé, imposer une convention explicite comme \`v<version>-linux\`, vérifier que le nom/version du binaire concorde avec le tag et échouer avant toute publication en cas d'écart. Ajouter un test automatisé couvrant ce cas précis. Ne pas renommer rétroactivement les anciennes releases sans vérifier le contenu exact de leurs artefacts.

### A-03 — Les tests de packaging ne vérifient pas toutes les dépendances livrées (**P1**)

**Fichier :** [\`.github/workflows/build-linux.yml\`](.github/workflows/build-linux.yml)

Le workflow exécute \`ldd\` sur \`usr/bin/LetsGoRecomp\`, vérifie la présence de plusieurs bibliothèques FFmpeg, puis extrait l'AppImage avec \`--appimage-extract\` et relance \`ldd\` sur le binaire principal extrait. C'est utile, mais le bundle contient aussi le générateur PyInstaller \`lasgen/lasgen\` et Zig ; le workflow ne vérifie pas explicitement les dépendances ELF de chaque binaire/extension native dans ces sous-répertoires. Il ne lance pas non plus le fichier AppImage lui-même en mode \`APPIMAGE_EXTRACT_AND_RUN=1\`.

**Impact :** une dépendance manquante du générateur ou du compilateur livré peut apparaître seulement sur la machine d'un utilisateur, lors de la première compilation du jeu. L'extraction réussie ne prouve pas que le runtime AppImage démarre correctement.

**Correction :**
1. Parcourir tous les fichiers ELF de l'AppDir et vérifier leurs dépendances avec \`lddtree\` ou une routine contrôlée basée sur \`ldd\`, en vérifiant aussi les extensions natives de PyInstaller.
2. Ajouter un test de démarrage automatisé dans un environnement Linux isolé (par exemple Xvfb et un backend Vulkan logiciel quand il est disponible) ou introduire un mode \`--self-test\` sans jeu/données. Distinguer explicitement un échec de dépendance d'un échec dû à l'absence de GPU.
3. Garder une vérification des bibliothèques hôte attendues : le chargeur/driver Vulkan et l'intégration graphique/audio doivent rester fournis par le système, plutôt que d'embarquer par erreur un pilote propriétaire.

### A-04 — Téléchargements de build non tous vérifiés par SHA-256 (**P1**)

**Fichier principal :** [\`.github/workflows/build-linux.yml\`](.github/workflows/build-linux.yml)

Le script [\`tools/fetch_zig.sh\`](tools/fetch_zig.sh) vérifie correctement le SHA-256 de l'archive Zig. D'autres étapes téléchargent cependant des composants exécutés pendant le build sans vérification explicite d'une somme publiée/pinnée : FFmpeg 6.1.6, l'AppImage \`linuxdeploy\`, le script \`llvm.sh\`, et certains fichiers de dépendances récupérés via URL. Les dépendances clonées par tags, notamment SDL, shaderc et Vulkan-Headers, utilisent des tags/release fixes mais ne sont pas toujours verrouillées sur des SHA de commit.

**Impact :** un changement de ressource distante ou une compromission en amont peut modifier le contenu du binaire publié tout en laissant le workflow vert.

**Correction :** préférer des archives de release avec SHA-256 attendu, figer les actions GitHub par SHA de commit, utiliser des commits de dépendances explicites lorsque c'est réaliste, et vérifier les signatures/provenances disponibles. Pour les composants système, documenter clairement les versions réellement résolues par l'image Ubuntu et conserver un manifeste complet de build.

### A-05 — Compilation coûteuse et environnement Python non verrouillé (**P2**)

**Fichiers :** [\`.github/workflows/build-linux.yml\`](.github/workflows/build-linux.yml), [\`tools/lasgen.spec\`](tools/lasgen.spec), [\`Makefile\`](Makefile)

Chaque build installe le toolchain LLVM, reconstruit FFmpeg, shaderc et SDL3 depuis les sources, puis installe les paquets Python \`capstone\`, \`unicorn\`, \`lz4\` et \`pyinstaller\` sans versions ni hashes. Il n'y a pas de cache explicite de téléchargements ou de compilation dans le workflow Linux. Le \`make -j2\` semble volontairement conservateur pour limiter la mémoire, mais aucune mesure par étape n'est publiée pour décider où le parallélisme est sûr.

**Impact :** temps de CI, consommation de minutes, dépendances résolues différemment entre deux runs et difficulté à reproduire un artefact ancien.

**Correction :** ajouter un fichier de dépendances Python versionné (idéalement verrouillé avec hashes), activer le cache pip, mettre en cache les archives de sources après vérification de leurs hashes et envisager \`ccache\` pour les objets C/C++. Clés de cache : OS/architecture, version du compilateur et hash de la définition des dépendances. Ne pas réutiliser un répertoire \`build/\` complet sans clé stricte. Mesurer d'abord les étapes avant de relever \`-j2\`.

### A-06 — Licences de composants embarqués : couverture à terminer (**P2**)

**Fichiers :** [\`.github/workflows/build-linux.yml\`](.github/workflows/build-linux.yml), [\`README.md\`](README.md), [\`LICENSE\`](LICENSE), [\`LICENSE-LASRecomp\`](LICENSE-LASRecomp), [\`tools/lasgen.spec\`](tools/lasgen.spec)

L'AppDir ajoute des notices pour FFmpeg, SDL3, VMA, Vulkan-Headers, shaderc, glslang et SPIRV-Tools, et dépose les licences du projet sous \`usr/bin\`. Le générateur PyInstaller embarque aussi des binaires/librairies de Capstone et Unicorn ; le runtime utilise également Dear ImGui, SMAA, stb, bcdec, la police Baloo 2 et des composants FidelityFX. Le dépôt contient plusieurs licences de ces projets, mais le script de staging ne les copie pas toutes explicitement dans \`usr/share/licenses/LetsGoRecomp\`.

**Impact :** l'archive livrée peut ne pas présenter toutes les notices pertinentes de chaque composant embarqué. Ce constat nécessite une matrice de composants→licence générée à partir des binaires réellement présents, pas une supposition sur les dépendances.

**Correction :** établir un inventaire des composants et de leurs modes de liaison (statique, dynamique, binaire distribué), puis copier les licences applicables dans l'AppDir et l'archive tar.gz. Générer un SBOM SPDX ou CycloneDX à chaque build et vérifier automatiquement que tout composant livré a sa notice. Vérifier en particulier les dépendances de \`lasgen\` et les licences des contenus embarqués dans \`runtime\`.

### A-07 — Documentation utilisateur et commentaires de build désynchronisés (**P2**)

**Fichiers :** [\`README.md\`](README.md), [\`Makefile\`](Makefile), [\`docs/release-README.txt\`](docs/release-README.txt), [\`.github/workflows/build-linux.yml\`](.github/workflows/build-linux.yml)

Le README principal décrit d'abord une distribution Windows ZIP et annonce Windows 10/11. Le workflow Linux fournit déjà des artefacts AppImage et tar.gz, alors que le commentaire d'en-tête du Makefile qualifie encore la branche Linux de « kept but untested here ». Le README intégré au paquet Linux expose ses exigences et le caractère expérimental, mais ce parcours n'est pas aisément visible depuis le README principal.

**Correction :** garder un statut explicite « expérimental » tant qu'un test gameplay sur Linux n'a pas été réalisé ; ajouter une section Linux qui décrit CPU, GLIBC ≥ 2.35, Vulkan/driver, FUSE 2 ou \`APPIMAGE_EXTRACT_AND_RUN=1\`, le chemin des données et le lien vers les artefacts. Corriger les commentaires du Makefile pour qu'ils distinguent plateforme compilable, plateforme testée en CI et plateforme validée en jeu.

### A-08 — Les tests ne couvrent pas l'ensemble du contrat de livraison (**P2**)

**Fichiers :** [\`.github/workflows/build-linux.yml\`](.github/workflows/build-linux.yml), [\`runtime/gamebuild.c\`](runtime/gamebuild.c), [\`runtime/paths.c\`](runtime/paths.c), [\`runtime/platform/linux.c\`](runtime/platform/linux.c), [\`tools/test_output_scale.c\`](tools/test_output_scale.c)

Le workflow construit le runtime et le générateur, produit le bundle et fait un contrôle de dépendances. La CI ne démontre pas, à elle seule, le chemin complet « AppImage → sélection des données utilisateur → génération de la bibliothèque du jeu avec Zig → lancement du jeu » ; les fichiers de jeu ne doivent d'ailleurs pas être inclus dans CI ni dans les releases. La revue n'a pas exécuté de session de jeu.

**Correction :** isoler des tests non dépendants du dump : résolution de la racine XDG, écriture du log, découverte des ressources à côté du binaire, sélection des outils, création d'un répertoire de travail, comportement en cas de dépendance manquante. Ajouter une vérification de régression ciblée pour les chemins Linux et un test de packaging qui contrôle le contrat de fichiers attendu. La validation gameplay doit rester un test manuel explicite et documenté, avec une copie légitime des données du testeur.

### A-09 — Résolution de chemins implémentée à deux endroits (**P3**)

**Fichiers :** [\`runtime/platform/linux.c\`](runtime/platform/linux.c), [\`runtime/paths.c\`](runtime/paths.c), [\`runtime/paths.h\`](runtime/paths.h)

Le logging précoce de \`plat_init()\` détermine le chemin du log avant \`rt_paths_init()\`, puis \`rt_paths_init()\` choisit la racine de données et change le répertoire courant. Les deux chemins connaissent \`LARECOMP_DATA_ROOT\`, \`XDG_DATA_HOME\` et \`HOME\`, mais avec des conditions distinctes (notamment le mode développeur pour le log).

**Impact :** les futures modifications de la politique XDG peuvent faire diverger l'emplacement du log et celui des saves/configurations.

**Correction :** conserver la phase de logging précoce, mais définir la politique de chemin comme contrat documenté et partagé (petit helper indépendant de SDL ou test unitaire des mêmes cas). Couvrir explicitement : variable XDG absolue, variable XDG relative ignorée, HOME manquant, répertoire de développement avec \`extracted/\`, \`LARECOMP_DATA_ROOT\` et chemin non inscriptible.

### A-10 — Plateforme réellement publiée à distinguer des cibles possibles (**P3**)

**Fichiers :** [\`Makefile\`](Makefile), [\`tools/fetch_zig.sh\`](tools/fetch_zig.sh), [\`.github/workflows/build-linux.yml\`](.github/workflows/build-linux.yml)

Le Makefile prévoit des réglages d'architecture Linux et le script Zig connaît les cibles \`x86_64-linux\` et \`aarch64-linux\`. Le workflow et les noms de sortie sont cependant exclusivement \`linux-x86_64\` sur \`ubuntu-22.04\`. Cela n'est pas un bug en soi, mais la capacité de compilation de certains sous-composants ne vaut pas support produit ARM64.

**Correction :** annoncer explicitement Linux x86_64 comme cible livrée. Ouvrir une cible ARM64 séparée seulement après avoir validé compilation, empaquetage, dépendances natives, CPU/ABI et tests d'exécution sur un runner correspondant.

## 3. Inventaire des fichiers par zone

L'inventaire Git comprend **458 fichiers suivis et 88 entrées de répertoire**. Les fichiers générés et données personnelles du jeu sont ignorés par Git ; il n'y a pas de dossier \`generated/\` ni \`extracted/\` dans le tree audité.

### Racine — 8 fichiers

| Fichier | Fonction / audit |
|---|---|
| \`.gitattributes\` | LF global, CRLF pour scripts Windows, fichiers médias binaires : configuration cohérente. |
| \`.gitignore\` | Exclut dumps \`.xci/.nsp/.nca/.nso\`, clés, \`extracted/\`, code généré, builds, saves, caches et logs : bon garde-fou pour éviter d'ajouter des données de jeu. |
| \`CHANGELOG.md\` | Historique principal des changements ; vérifier que toute release publiée est décrite et concorde avec les artefacts. |
| \`CONTRIBUTING.md\` | Guide de contribution ; compléter si nécessaire avec le parcours de test CI Linux. |
| \`LICENSE\` | Licence du dépôt ; ne remplace pas les notices des dépendances tierces. |
| \`LICENSE-LASRecomp\` | Notice amont conservée séparément. |
| \`Makefile\` | Build principal Windows/Linux, génération du jeu, compilation runtime et distribution Windows. Commentaire Linux d'en-tête dépassé ; cibles Linux pas exposées comme release locale dédiée. |
| \`README.md\` | Documentation principale utilisateur ; actuellement orientée Windows malgré les artefacts Linux. |

### CI / release — 2 fichiers

| Fichier | Fonction / audit |
|---|---|
| \`.github/workflows/build-linux.yml\` | Installe toolchains et bibliothèques, compile le runtime, construit \`lasgen\`, récupère Zig, assemble AppDir/AppImage/tar.gz et checksums. Build actuel réussi ; améliorer pinning, caches, tests ELF et smoke test. |
| \`.github/workflows/publish-linux.yml\` | Publication manuelle séparée. Bon : valide run réussi et checksums, refuse un tag ayant déjà une release. À corriger : commit cible, événement/branche acceptés, cohérence tag/version, test robuste d'existence du tag et permissions au niveau job. |

### Documentation et assets — 30 fichiers sous \`docs/\`

| Groupe | Fichiers / appréciation |
|---|---|
| Architecture / audit | \`ANALISE-LASRecomp.md\`, \`technical-audit.md\`, \`DIAGNOSTICO.md\` : architecture, diagnostic et hypothèses techniques utiles ; garder les constats « hypothèse » distincts des bugs reproduits. |
| Build / dépannage | \`COMPILAR-WINDOWS.md\`, \`DEPURACAO.md\`, \`release-README.txt\` : procédures Windows et distribution. Ajouter le parcours Linux dans un document dédié ou dans le README principal. |
| Progression / historique | \`HISTORICO.md\`, \`PROGRESSO.md\`, \`ROADMAP.md\`, \`MODO-BATALHA.md\`, \`PLANO-3D.md\` : notes de développement ; volumineuses et utiles à conserver hors de la documentation de démarrage. |
| Performance / recherche | \`PESQUISA-60FPS.md\`, \`PESQUISA-GPU.md\`, \`native-60fps-research.md\`, \`performance-analysis.md\`, \`graphics-improvements.md\` : recherche et analyses ; distinguer les résultats reproduits des pistes. |
| Visuels de documentation | \`viridian.jpg\`, \`shots/{battle,catch,eevee,ptbr,video}.jpg\`, \`images/{f12-menu.jpg,launcher-game.png,launcher-graphics.png,launcher-mods.png}\` : visuels du README et des docs, pas dépendances de l'exécution principale. |
| Icônes | \`icon/{icon.icns,icon.ico,icon.svg,icon_1024.png}\` : ressources macOS, Windows, vectorielle et PNG ; le workflow Linux dérive son icône 512×512 du PNG 1024. |

### Police — 1 fichier

- \`fonts/README.md\` : consignes de police issue du système de l'utilisateur. \`.gitignore\` exclut les fichiers \`.bfttf\` et \`.ttf\` dans ce dossier ; vérification positive contre l'ajout accidentel de polices extraites.

### Runtime — 103 fichiers sous \`runtime/\`

| Zone | Fichiers / responsabilité |
|---|---|
| CPU et dispatch | \`cpu.h\`, \`simd.h\`, \`simd_fp.h\`, \`dispatch.c\`, \`fnhook.c\`, \`fnprof.c\`, \`storetrace.c\` : état CPU/FP/SIMD, appels indirects, hooks et instrumentation. À couvrir par tests différentiels et profils ; ne pas extrapoler la correction complète depuis la compilation. |
| Chargement / build | \`main.c\`, \`loader.c\`, \`gamebuild.c/.h\`, \`gamelib.c/.h\`, \`gamesetup.c/.h\`, \`romfs_build.c/.h\` : boot, chargement, ID de bibliothèque, génération à la demande et préparation du jeu. \`gamebuild.c\` dépend des ressources \`lasgen\`, Zig et \`gamelib-src\` livrées dans les bundles. |
| Configuration / chemins / mods | \`paths.c/.h\`, \`settings.c/.h\`, \`mods.c/.h\`, \`ui2x.c/.h\` : racine de données, ressources installées, settings et mods. Tester permissions et chemins avec espaces/symlinks ; conserver saves/config hors de l'AppImage en lecture seule. |
| Kernel / IPC / services | \`kernel.c/.h\`, \`ipc.c/.h\`, \`services/{acc,am,audio,fs,hid_set,hwopus,misc,network,offline,time}.c\`, \`hle.h\` : services de compatibilité hôte/guest. Les contrats de retour et chemins non implémentés nécessitent des tests en jeu ; compilation seule insuffisante. |
| HLE | \`hle/{bindings,catch_button,controller_skip,cutscene,font_hires,fps60,fps60_research,framepace,heaps,input,memscan,memwatch,movie,nvn_boot,pl,swkbd,vi,wildbattle}.c\`, \`hle/catch_button_art.h\`, \`hle/hle_symbols.txt\` : adaptations et correctifs du jeu. Distinguer recherche/expérimental des fonctionnalités validées. |
| NVN / rendu | \`nvn/{astc.c/.h,cmdbuf.c,formats.c,objects.c,output_scale.c/.h,renderer.h,smaa_data.c,tegra.c/.h,nvn.h}\`, \`nvn/maxwell/{shader.h,translate.c}\`, \`nvn/vulkan/{device.c,exec.c,fsr3.cpp/.h,imgui_glue.cpp,renderdoc.c,renderthread.c,shaders.c/.h,textures.c,vk.h,vma.cpp}\` : traduction des commandes, shaders, allocations et renderer Vulkan. \`exec.c\` est un très gros module (≈440 KB) et mérite des tests ciblés/perf captures ; aucune optimisation de barrières ne doit être faite sans mesure. |
| Plateforme | \`platform.h\`, \`platform/linux.c\`, \`platform/linux_compat.h\`, \`platform/windows.c\`, \`platform/win_compat.h\`, \`platform/windows.manifest\`, \`platform/windows.rc\`, \`platform/windows_threads.h\` : abstraction hôte. Linux réserve l'espace invité, gère l'horloge, les processus, les logs et la détection CPU ; ajoutez des smoke tests autour de l'environnement AppImage. |
| UI | \`ui/{launcher_lg.mm,menu.h,menu.mm,osk.h,osk.mm,settings_ui.h}\` : launcher, menu in-game, clavier et settings. Compilé comme C++ par le Makefile sur Linux ; maintenir un test de compilation de cette voie. |
| Autres | \`input_bind.h\` et fichiers de service cités ci-dessus : interfaces partagées. Les headers doivent rester compatibles avec les deux toolchains, Linux et Windows. |

### Outils — 54 fichiers sous \`tools/\`

| Groupe | Fichiers | Audit / usage |
|---|---|---|
| Générateur / traducteur | \`gen.py\`, \`lifter.py\`, \`analyze.py\`, \`nso.py\`, \`passes.py\`, \`patches.py\`, \`simd_c.py\`, \`gamelib_entry.c\`, \`lasgen.spec\`, \`README-gen.md\` | Chemin critique : outil PyInstaller produit dans \`build/helper/lasgen\`, appelé lors de la création locale du code de jeu. Verrouiller les dépendances et tester la commande avec un fixture non propriétaire. |
| Zig / dépendances / build | \`fetch_zig.sh\`, \`zig_slim.sh\`, \`build_deps_windows.sh\`, \`setup_windows.ps1\`, \`winseries.ps1\` | Zig vérifie son hash ; reproduire la même discipline pour chaque téléchargement Linux. Les scripts Windows sont hors du chemin AppImage mais font partie du contrat multi-plateforme. |
| Analyse binaire / xrefs | \`addr2sym.py\`, \`addrmap.py\`, \`disasm.py\`, \`nso.py\`, \`xrefs.py\`, \`mv_check.py\`, \`mv_errmap.py\`, \`pe_no_cfg.py\` | Outils d'analyse/recherche et préparation Windows ; séparer des étapes exigées en build de celles réservées à l'investigation. |
| Performance / captures | \`analyze.py\`, \`bateria.sh\`, \`bateria_scan.py\`, \`blink_scan.py\`, \`capture_loop.py\`, \`contact_sheet.py\`, \`extract_glsl.py\`, \`fg_walk.sh\`, \`fncompare.py\`, \`frametime_summary.py\`, \`interp_metrics.py\`, \`perf_ab.py\`, \`perf_summary.py\`, \`rdc_draw.py\`, \`rdc_skin.py\`, \`scenario_shot.sh\`, \`scroll_speed.py\`, \`shader_inventory.py\`, \`ssao_temporal_check.py\`, \`ssao_temporal_sheet.py\`, \`test_output_scale.c\`, \`teste60.sh\`, \`trace_run.sh\`, \`ui_texkeys.py\`, \`walk_speed.sh\`, \`winshot.ps1\` | Boîte à outils de recherche. Les scripts qui effacent/régénèrent des dossiers de test doivent annoncer leurs effets destructifs et être exécutés uniquement sur une copie de save. |
| Extraction / génération d'assets | \`catch_button.py\`, \`catch_button_art.py\`, \`make_icons.py\`, \`shader_inventory.py\`, \`ui_texkeys.py\` | Génération d'assets ou index ; documenter les entrées et résultats attendus, ne pas confondre artefacts régénérables et sources de référence. |
| Divers / reproduction | \`publicar_jogo.sh\`, \`repro.sh\`, \`trace_run.sh\`, \`walk_speed.sh\`, \`fg_walk.sh\`, \`lasgen.spec\` et scripts de test listés ci-dessus | À garder distinct du build release. Les scripts de reproduction devraient être documentés comme outils développeur, avec prérequis et zones supprimées. |

> Les groupes d'outils ci-dessus se chevauchent volontairement par usage ; le total de 54 correspond aux fichiers réels du dossier, pas à la somme des lignes du tableau.

### Dépendances tierces — 260 fichiers sous \`third_party/\`

| Composant | Contenu observé | Recommandation |
|---|---|---|
| \`third_party/imgui/\` | Dear ImGui, backend SDL3/Vulkan utilisé par le build, mais aussi de nombreux backends, exemples, projets et bibliothèques GLFW tiers inutilisés par ce Makefile. | Ne pas patcher le vendored en masse sans besoin. Documenter le commit/version source ; éventuellement réduire les fichiers non nécessaires dans une modification séparée si la maintenance et les licences le permettent. |
| \`third_party/fidelityfx/\` | Headers API FidelityFX et DLL Windows \`amd_fidelityfx_vk.dll\` (≈9,3 MB). | Garder la DLL Windows hors de l'AppImage ; ajouter la notice si un composant FidelityFX correspondant est distribué côté Linux. |
| \`third_party/smaa/\` | Shader SMAA, textures et licence. | Généré dans \`build/\` par le Makefile à partir du shader ; préserver les fichiers source et la notice. |
| \`third_party/stb/\` | \`stb_image.h\`, \`stb_image_write.h\`, \`stb_dxt.h\`. | Inclure l'avis de licence pertinent dans le bundle/manifest. |
| \`third_party/bcdec/\` | \`bcdec.h\` et licence. | Confirmer le mode d'inclusion et inclure sa notice. |
| \`third_party/fonts/Baloo2/\` | Police SemiBold et OFL. | L'OFL est déjà copiée ; conserver la notice à proximité de la police. |

## 4. Fichiers de packaging Linux : contrat attendu

L'AppDir assemblé par \`.github/workflows/build-linux.yml\` contient aujourd'hui, au minimum :

- \`usr/bin/LetsGoRecomp\` : runtime principal ;
- \`usr/bin/lasgen/\` : générateur PyInstaller onedir ;
- \`usr/bin/zig/\` : toolchain Zig épurée par \`tools/fetch_zig.sh\` ;
- \`usr/bin/gamelib-src/\` : headers/interfaces utilisés pour recompiler le code du jeu de l'utilisateur ;
- \`usr/share/applications\`, icône 512×512, \`.DirIcon\`, \`AppRun\`, wrapper \`LetsGoRecomp\` ;
- \`usr/share/licenses/LetsGoRecomp/\` : licences d'une partie des dépendances ;
- un README Linux décrivant GLIBC ≥ 2.35, Vulkan 1.3, dépendances graphiques/audio hôte et FUSE 2.

Les répertoires \`extracted/\`, \`generated/\`, les saves, settings, mods et caches de shader ne doivent pas être intégrés au bundle. Ils doivent rester dans la racine de données de l'utilisateur ; \`runtime/paths.c\` utilise \`$XDG_DATA_HOME/lasrecomp\` ou \`~/.local/share/lasrecomp\` hors mode développeur. Il ne faut pas embarquer le chargeur Vulkan ni les pilotes du système.

## 5. Vérifications recommandées avant une release

- [ ] Le tag de release est absent avant publication et respecte le schéma de version retenu.
- [ ] Le run de build est terminé avec succès, a l'événement/branche autorisés et son SHA est celui ciblé par le tag.
- [ ] Tag, \`RT_APP_VERSION\`, nom de bundle et version affichée concordent.
- [ ] SHA-256 recalculés pour l'AppImage et l'archive ; manifeste de fichiers et provenance joints.
- [ ] Tous les ELF livrés (runtime, Zig, helper et extensions natives) ont des dépendances résolues selon la politique hôte/embarquée.
- [ ] AppImage extrait correctement ; mode \`APPIMAGE_EXTRACT_AND_RUN=1\` testé sur une machine sans FUSE 2 quand possible.
- [ ] Parcours de démarrage de l'application testé sans dump du jeu ; parcours de génération du jeu documenté séparément et sans données propriétaires dans les artefacts.
- [ ] Toutes les licences et le SBOM sont présents dans chaque format distribué.
- [ ] README, notes de release et checksum pointent sur les mêmes versions.
- [ ] Statut de test gameplay Linux (non validé / partiellement validé / validé) explicite.

## Conclusion

Le dépôt dispose déjà d'un pipeline Linux relativement complet et le dernier build sur \`main\` passe. La première itération de correction devrait se concentrer sur **l'intégrité de la release (A-01/A-02), la validation du contenu ELF livré (A-03), puis le pinning des dépendances (A-04)**. Les caches et la couverture de tests viennent ensuite ; les optimisations de taille ou du runtime ne devraient être engagées qu'avec des mesures reproductibles.
