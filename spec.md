# Plan d'optimisation — AppImage, CI et distribution Linux

- **Dépôt :** [rakmahefa/letsgo-recomp](https://github.com/rakmahefa/letsgo-recomp)
- **Base analysée :** \`main\`, commit \`bdde3ad1036e47bcb109b47ff887cef512690059\` (2026-10-26)
- **Objectif :** rendre la distribution Linux plus fiable, vérifiable, reproductible et simple à maintenir avant d'investir dans des optimisations agressives de taille ou de temps de compilation.
- **Périmètre produit immédiat :** AppImage et archive autonome Linux **x86_64**. ARM64 reste une cible distincte à valider, pas une promesse de distribution.

## 1. Priorités

| Priorité | Travail | Pourquoi | Livrable |
|---|---|---|---|
| **P0 — release integrity** | Lier le tag au SHA du build, valider la version et empêcher les tags déjà existants | Éviter qu'une release annonce une version/commit différent du binaire livré | Workflow de publication durci + tests de validation |
| **P1 — packaging correctness** | Vérifier les dépendances ELF de tous les exécutables livrés et tester le chemin AppImage | Le runtime principal n'est pas le seul programme exécuté : le générateur et Zig sont nécessaires au setup local | Smoke tests de bundle réutilisables |
| **P1 — supply chain** | Vérifier hashes/signatures, verrouiller les dépendances et réduire les actions non pinnées | Construire depuis des entrées explicites et auditables | Manifest de dépendances + hashes + pinning |
| **P1 — metadata/legal** | Aligner tag, version, notes, licence, checksum et SBOM | Rendre l'artefact identifiable et redistribuable dans de bonnes conditions | Manifeste de release et notices complètes |
| **P2 — CI time** | Mesurer puis mettre en cache téléchargements et compilations sûres | Éviter de rebâtir systématiquement les mêmes dépendances | Temps par étape publiés, caches à clé stricte |
| **P2 — test coverage** | Tester chemins XDG, ressource du binaire, helper, Zig et échec contrôlé | La compilation ne valide pas le premier démarrage d'un utilisateur | Tests automatiques indépendants des ROM |
| **P2 — utilisateur/docs** | README Linux, prérequis hôte et procédure de dépannage | L'utilisateur doit comprendre les limites avant téléchargement | Section Linux cohérente avec les artefacts |
| **P3 — taille/architecture** | Réduire Zig uniquement si mesuré, clarifier la cible ARM64 | Éviter une optimisation de taille qui casse la recompilation à la première exécution | Rapport de taille et décision documentée |

## 2. P0 — Version, tag et provenance des artefacts

### 2.1 Une seule source de version

Aujourd'hui, la version d'exécution est définie dans \`runtime/paths.h\` via \`RT_APP_VERSION\`; le build Linux construit les noms d'artefacts à partir de cette valeur alors que la publication accepte un tag manuel libre. Des releases visibles portent un tag \`v0.6.x-linux\` avec des fichiers \`LetsGoRecomp-0.5.0-linux-x86_64.*\`, tandis que la source analysée indique \`0.7.5\`.

**Spécification :**
1. La version source est lue depuis \`RT_APP_VERSION\` pendant le build.
2. L'artefact contient un fichier texte généré automatiquement, par exemple \`BUILD-INFO.txt\`, avec version, commit SHA, branche, architecture, date UTC du build et version du toolchain.
3. Le workflow de release télécharge uniquement les artefacts d'un run accepté.
4. Le tag et la version de bundle doivent suivre une convention définie : \`v<version>-linux\` pour les releases Linux, ou une autre convention unique documentée. Ne pas mélanger plusieurs règles.
5. En cas de mismatch, le workflow échoue **avant** création de la release.
6. Le SHA de source attaché au tag doit être le même que le \`headSha\` du run de build sélectionné.

### 2.2 Valider le run sélectionné

Dans \`.github/workflows/publish-linux.yml\`, valider explicitement, en plus de \`status=completed\`, \`conclusion=success\` et \`workflowName=Linux native build\` :

- le dépôt attendu ;
- les événements acceptés (par défaut, uniquement un \`push\` autorisé ; exclure les runs \`pull_request\` pour une release) ;
- la branche autorisée, par exemple \`main\` ou une branche de release explicitement permise ;
- le SHA de commit qui sera la cible du tag ;
- la version embarquée dans \`BUILD-INFO.txt\` et le nom de chaque artefact.

Créer le tag/release avec la cible de commit du run validé — ne pas dépendre de la tête actuelle de la branche par défaut. Enregistrer ce SHA dans les notes ou comme fichier joint.

### 2.3 Vérifier l'existence d'un tag séparément

Le test actuel basé sur \`gh release view "$TAG"\` protège contre une release déjà existante, mais ne démontre pas qu'un tag Git du même nom n'existe pas sans release. Ajouter un contrôle spécifique du ref Git. Ne poursuivre que si le ref est réellement absent ; ne pas traiter un échec réseau/API comme une preuve d'absence.

### 2.4 Réduire les permissions

Déplacer les permissions d'écriture de contenu au job \`publish\`, et garder le job de validation de syntaxe et les builds en lecture seule. Les événements PR ne devraient jamais avoir besoin du droit \`contents: write\`. Conserver \`actions: read\` uniquement là où il faut inspecter/télécharger un run.

**Critères d'acceptation :**
- Un tag déjà présent — même sans release associée — bloque le job.
- Un run PR, un run d'une branche non permise ou un run échoué bloque la publication.
- Un artefact 0.5.0 ne peut pas être publié sous un tag 0.6.1/0.7.5.
- Le tag pointe sur le SHA du run de build.
- Les checksums sont recalculés avant publication ; les assets sont publiés seulement si tous les contrôles passent.
- Les tests négatifs des versions et du tag sont automatisés avec des fixtures/mocks, sans publier réellement de release.

## 3. P1 — Packaging AppImage robuste

### 3.1 Contrat du bundle

Garder le format actuel avec \`usr/bin/LetsGoRecomp\`, \`lasgen/\`, \`zig/\`, \`gamelib-src/\`, un \`AppRun\`, l'entrée desktop, l'icône et les notices. Garder les données modifiables hors du bundle : \`extracted/\`, sauvegardes, mods, configuration et cache shader sont des données de l'utilisateur.

| Élément | Règle |
|---|---|
| Runtime principal | Dépendances nécessaires présentes ; aucune bibliothèque accidentellement résolue depuis le répertoire \`build/\` du runner. |
| Vulkan | Garder le chargeur/driver Vulkan et le pilote GPU comme prérequis système. Ne pas inclure un pilote du runner dans l'AppImage. |
| SDL et FFmpeg | Embarquer les versions attendues, et contrôler leurs SONAMEs ainsi que la résolution réelle des bibliothèques. FFmpeg doit rester la build LGPL-only configurée par le workflow. |
| \`lasgen\` | Vérifier l'exécutable PyInstaller, toutes les extensions natives Capstone/Unicorn et leurs dépendances dynamiques. |
| Zig | Vérifier le binaire, les headers et libc sources nécessaires à \`zig cc\` sur le système supporté ; ne pas supprimer de fichiers sans test de génération/link. |
| Ressources | Vérifier les fichiers \`gamelib-src\`, la police, les icônes et les licences présentes, avec une liste attendue versionnée. |
| Données utilisateur | Vérifier le répertoire XDG et la possibilité d'écrire en dehors du point de montage AppImage. |

### 3.2 Vérification ELF de tous les exécutables

Ajouter une étape unique après assemblage de l'AppDir :

1. Identifier chaque exécutable ELF et chaque extension native avec \`file\`/la signature ELF, sans traiter les fichiers de données comme des binaires.
2. Examiner la résolution dynamique avec \`lddtree\` ou un équivalent contrôlé pour :
   - \`usr/bin/LetsGoRecomp\` ;
   - \`usr/bin/zig/zig\` ;
   - \`usr/bin/lasgen/lasgen\` ;
   - les bibliothèques natives chargées par PyInstaller.
3. Faire échouer le build si une dépendance attendue comme embarquée est introuvable ou vient d'un chemin non autorisé.
4. Maintenir une allowlist documentée des bibliothèques hôte : Vulkan loader/driver, stack graphique et audio, libc/GLIBC et intégration desktop.
5. Archiver les rapports de dépendances comme artefacts CI de diagnostic.

Ne pas se limiter à grepper le texte \`not found\` d'un seul \`ldd\` ; un rapport structuré par fichier binaire est préférable.

### 3.3 Smoke tests AppImage

La vérification actuelle extrait l'AppImage et contrôle \`AppRun\` plus le binaire principal. Étendre-la en étapes distinctes :

- **structure** : extraction, fichiers requis, permissions exécutables, icône et fichier desktop valides ;
- **dépendances** : contrôle ELF complet de l'AppDir extrait ;
- **lanceur** : lancer le vrai AppImage avec \`APPIMAGE_EXTRACT_AND_RUN=1\` dans un runner ou conteneur de test ;
- **ressources** : confirmer que les ressources sont résolues depuis le bundle, et non depuis la racine source ;
- **données** : avec HOME/XDG temporaires, vérifier que logs/configuration sont créés à l'emplacement attendu ;
- **setup sans jeu** : confirmer que l'absence des données de jeu produit un message d'erreur contrôlé et n'écrit aucun fichier propriétaire.

Si une validation nécessite un serveur graphique ou un Vulkan ICD, l'installer explicitement dans l'environnement de test. Si elle ne peut pas être exécutée dans le runner, la déclarer « non validée » plutôt que présenter l'extraction comme un test de lancement.

Un mode \`--version\`/ \`--self-test\` sans jeu serait utile pour rendre les tests reproductibles et éviter d'automatiser des clics UI fragiles.

### 3.4 FUSE 2 / mode d'extraction

Le bundle annonce une solution de repli \`APPIMAGE_EXTRACT_AND_RUN=1\`. Tester ce mode dans la CI et documenter la commande exacte dans le README Linux. L'existence de ce fallback ne remplace pas les tests sur un système réel sans FUSE 2.

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

- Réutiliser le modèle de \`tools/fetch_zig.sh\`, qui vérifie déjà un SHA-256 attendu.
- Ajouter le SHA-256 attendu des archives FFmpeg et de linuxdeploy, et vérifier avant extraction/exécution.
- Pour les téléchargements VMA/header/license et autres fichiers raw, pinner le contenu par checksum.
- Remplacer l'exécution de \`llvm.sh\` non figé par une méthode documentée dont l'identité/version est verrouillée, ou pinner/vérifier son contenu et la version exacte de Clang installée.
- Préférer un commit explicite pour les clones de sources, même si l'URL utilise aussi un tag lisible.
- Pinner les GitHub Actions externes par SHA immuable et utiliser une politique automatisée de mise à jour des pins.
- Verrouiller le set Python, idéalement versions + hashes via un fichier de lock. Une simple mise à niveau de \`pip\` à la dernière version rend les environnements temporellement variables.

Ne pas confondre « même nom de version » avec « octets identiques » ; le contrôle doit échouer avant d'exécuter une archive qui n'a pas le hash attendu.

### 4.3 Manifeste de build et provenance

Générer un artefact \`build-manifest.json\` (ou JSON équivalent versionné) contenant :
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
| \`ccache\` pour C/C++ | OS + version exacte de Clang + options + hash dépendances | Toolchain, flags ou headers source changés |
| Artefacts compilés SDL/shaderc/FFmpeg | OS + architecture + compiler ID + versions/options | Invalider dès qu'une dépendance ou option de configuration change |
| PyInstaller | Lock Python + version de PyInstaller + hash du spec et des scripts | Lock/spec/scripts changés |

Utiliser une action de cache elle-même pinnée. Éviter de mettre en cache l'intégralité de \`build/\` sous une clé trop large : un objet compilé avec un ancien header ou un mauvais flag peut produire une panne difficile à diagnostiquer. Il faut conserver le test de dépendances et le smoke test après cache.

### 6.3 Parallélisme

Le \`make -j2\` du workflow est conservateur. Ne l'augmenter qu'après mesure de la mémoire maximale des étapes FFmpeg/shaderc et du runtime. Si la compilation est limitée par mémoire, rendre le nombre de jobs explicite (par exemple une variable CI) et garder une limite sûre par défaut. Ne pas optimiser au détriment de la reproductibilité.

### 6.4 Séparer validation rapide et packaging complet

Créer au besoin deux chemins :
- **validation rapide PR** : format/validation YAML, compilation runtime sur les sources pertinentes, tests de scripts et headers, tests unitaires sans dépendance aux dumps ;
- **bundle complet** : toolchain complète, AppDir/AppImage, checksums, rapport ELF, SBOM, artefacts téléchargeables.

Le packaging complet doit continuer d'être exécuté au moins sur les changements runtime, Makefile, scripts de génération, dépendances et workflows. Ne pas ignorer un changement de \`tools/\` ou \`third_party/\` qui affecte l'artefact.

## 7. P2 — Couverture de tests sans données du jeu

L'absence de ROM dans la CI est intentionnelle : le dépôt et les artefacts ne doivent pas inclure de données propriétaires. Les tests ci-dessous ne nécessitent aucun dump.

| Test | Cible | Résultat attendu |
|---|---|---|
| Version et métadonnées | \`runtime/paths.h\`, workflow | La version du bundle, BUILD-INFO et le nom des artefacts sont identiques. |
| Contrat AppDir | \`build-linux.yml\` | Tous les chemins requis existent ; aucun dossier \`extracted/\`, \`generated/\`, save ou mod n'est inclus. |
| ELF / SONAME | AppDir extrait | Aucune dépendance embarquée manquante ; hôte autorisé clairement déclaré. |
| AppRun | \`AppRun\`, wrapper et AppImage | Le runtime est lancé depuis les chemins embarqués, sans dépendre du checkout ou du CWD. |
| XDG / données | \`runtime/paths.c\`, \`runtime/platform/linux.c\` | \`XDG_DATA_HOME\` absolu est respecté ; XDG relatif est ignoré ; HOME manquant et dossier non inscriptible produisent un résultat contrôlé. |
| Ressources | \`runtime/paths.c\`, \`runtime/gamebuild.c\` | \`lasgen\`, Zig et \`gamelib-src\` sont découverts depuis le package. |
| Helper | \`tools/lasgen.spec\` | Le générateur démarre et affiche l'aide/usage sans dépendre d'un Python du système ; vérifier les bibliothèques Capstone/Unicorn. |
| Zig | \`tools/fetch_zig.sh\` | Binaire et données de compilation présents, hash vérifié, commande compiler/link de probe fonctionnelle. |
| Échec contrôlé | Runtime sans données de jeu | Message clair, pas de crash obscur ni de fichiers de jeu/sauvegarde créés. |
| Checksums | Artefacts finaux | Les deux SHA-256 se vérifient depuis les fichiers téléchargés. |
| Licences / SBOM | Artefacts finaux | Chaque composant livré est documenté et possède sa notice requise. |

Ajouter ensuite une grille manuelle de validation gameplay Linux, distincte de la CI automatisée : Eevee/Pikachu, scènes de départ, save/load, audio, contrôleurs, transitions et GPU Vulkan. Le statut de cette grille doit figurer dans la documentation (non testé, partiellement testé, validé), sans déclarer un support de bout en bout sur la seule base de la compilation CI.

## 8. P2 — Documentation utilisateur et support

Mettre à jour \`README.md\` ou ajouter un \`docs/LINUX.md\` et le relier depuis le README.

Le guide Linux doit donner :
- statut expérimental actuel et limites fonctionnelles connues ;
- architecture livrée : x86_64 pour la release actuelle ;
- exigences annoncées par le bundle : GLIBC ≥ 2.35, CPU compatible avec les niveaux générés (vérifier la détection v2/v3), Vulkan 1.3, driver GPU compatible ;
- FUSE 2 et commande de repli \`APPIMAGE_EXTRACT_AND_RUN=1\` ;
- différence entre dépendances embarquées (SDL3, FFmpeg selon le build) et stack hôte (Vulkan/driver, graphiques/audio) ;
- emplacement de la configuration, des saves, des mods, du cache shader et des logs ;
- procédure de collecte de \`lasrecomp.log\`, distro, GPU/driver et résultat du test Vulkan ;
- procédure SHA-256 de vérification des téléchargements ;
- clause claire : les données du jeu doivent provenir de l'utilisateur, aucune donnée du jeu n'est fournie.

Mettre à jour les commentaires du Makefile qui qualifient le build Linux d'inutilisé/non testé, mais ne pas laisser entendre que le gameplay Linux est validé avant qu'il ne le soit.

## 9. P3 — Taille du bundle et optimisations de la toolchain

Les releases actuelles visibles contiennent un AppImage d'environ **87,5 MB** et une archive tar.gz d'environ **96,4 MB**. Ce sont des points de référence historiques ; mesurer les artefacts du nouveau commit avant d'en tirer une conclusion sur une régression.

### 9.1 Profiling du contenu

À chaque build de référence, publier un tableau \`du -sh\` par sous-répertoire et les plus gros fichiers :
- \`usr/bin/LetsGoRecomp\` ;
- \`usr/bin/lasgen\` et ses bibliothèques ;
- \`usr/bin/zig\` ;
- bibliothèques SDL/FFmpeg ;
- polices et assets ;
- données non exécutables et licences.

L'optimisation doit commencer là où la taille est réellement concentrée. Ne pas réduire la qualité de compression ou la compatibilité host pour une petite économie théorique.

### 9.2 Zig

\`tools/fetch_zig.sh\` télécharge Zig et enlève déjà des parties de libc qui ne correspondent pas à la cible. \`tools/zig_slim.sh\` construit une toolchain Windows spécialisée ; ce script n'est pas réutilisable tel quel sous Linux.

Évaluer un équivalent Linux uniquement si le rapport montre que Zig domine le bundle. Toute version réduite doit démontrer, sur une machine propre avec caches Zig vides :
- compilation de la bibliothèque générée ;
- linkage du shared object ;
- support des flags CPU retenus ;
- absence de recherche de headers/libc dans le checkout ou dans les dossiers du runner ;
- comportement après mise à jour de Zig.

Ne pas retirer arbitrairement \`lib/std\`, les headers glibc/musl requis, les sources de compiler-rt ou les composants utilisés implicitement par \`zig cc\`.

### 9.3 Réduction du checkout tiers

\`third_party/imgui/\` contient les backends, exemples et projets upstream qui ne sont pas tous compilés par le Makefile actuel. Cela alourdit surtout le checkout, pas forcément l'AppImage. La suppression n'est pas une priorité de release ; envisager un sous-ensemble seulement avec une procédure de mise à jour upstream, une liste claire des fichiers utilisés et les notices de licence intactes.

## 10. Support architecture et compatibilité

- **Cible de livraison actuelle :** \`linux-x86_64\`, construite sur \`ubuntu-22.04\` pour conserver le baseline GLIBC documenté.
- **Tests de compatibilité :** au minimum Ubuntu 22.04 et une distribution plus récente ; ajouter d'autres environnements représentatifs si des problèmes de dépendances hôte sont remontés.
- **ARM64 :** ne publier que si un runner natif/cross validé compile les dépendances et le runtime, construit l'AppImage correspondante, vérifie les ELF et fait un test de démarrage. Les noms d'artefact et le manifest doivent inclure l'architecture.
- **Vulkan :** les runners de compilation n'attestent pas la compatibilité avec tous les GPU. Séparer CI build, test logiciel de démarrage et validation réelle GPU.
- **GLIBC :** ne relever le baseline du runner qu'avec une décision de support/documentation ; sinon tester que les binaires ne dépendent pas d'une GLIBC plus récente que le minimum annoncé.

## 11. Séquence d'implémentation

### Étape 1 — sécuriser la release
- [ ] Ajouter \`BUILD-INFO.txt\` et version unique dans les artefacts.
- [ ] Valider branch/event/SHA/version du run de build.
- [ ] Créer les tags sur le SHA exact du build.
- [ ] Vérifier l'absence du tag Git, y compris sans release existante.
- [ ] Placer \`contents: write\` uniquement sur le job de publication.
- [ ] Ajouter des tests de versions mismatch et run non autorisé.

### Étape 2 — rendre le bundle testable
- [ ] Vérifier chaque ELF et ses dépendances dans l'AppDir.
- [ ] Ajouter un mode self-test/version ou un smoke test contrôlé.
- [ ] Lancer le véritable AppImage en test avec extraction de repli.
- [ ] Tester le helper et Zig sans utiliser les données du jeu.
- [ ] Garder une allowlist des bibliothèques hôte.

### Étape 3 — verrouiller les entrées et notices
- [ ] Ajouter les hashes de tous les téléchargements exécutés.
- [ ] Pinner les actions et commits de sources.
- [ ] Ajouter le lock Python.
- [ ] Générer manifeste et SBOM.
- [ ] Compléter le staging des licences et valider leur présence.

### Étape 4 — mesurer et accélérer
- [ ] Enregistrer les temps par étape et la taille par sous-répertoire.
- [ ] Activer pip cache, cache des archives vérifiées puis \`ccache\`.
- [ ] Comparer temps à cache chaud/froid.
- [ ] Augmenter le parallélisme seulement après mesure de la mémoire.
- [ ] Refaire les mêmes tests post-cache pour exclure une corruption incrémentale.

### Étape 5 — clarifier le support Linux
- [ ] Documenter AppImage et archive tar.gz dans le README.
- [ ] Documenter les dépendances hôte et FUSE 2.
- [ ] Corriger les commentaires Makefile périmés.
- [ ] Publier le statut réel de validation gameplay.
- [ ] Décider séparément si ARM64 devient une cible officielle.

## 12. Définition de terminé (DoD)

Une release Linux est prête lorsque :

1. un tag/version/commit cohérent est validé automatiquement ;
2. le build et les dépendances de chaque binaire embarqué passent les contrôles ;
3. l'AppImage se structure et démarre dans le scénario de test déclaré ;
4. le helper et Zig sont vérifiés avec un cache de compilation propre ;
5. les sommes SHA-256, manifest de build, provenance et SBOM sont publiés ;
6. chaque composant distribué dispose de la notice requise ;
7. README et note de release décrivent les exigences réelles et les limites connues ;
8. aucun dump, clé, save ou contenu propriétaire du jeu ne se trouve dans les artefacts.

**Ordre conseillé :** terminer d'abord l'intégrité de la release et les tests de packaging ; optimiser ensuite les temps et la taille. Tant que la version livrée et son commit ne sont pas liés de façon vérifiable, réduire quelques mégaoctets ou quelques minutes n'est pas le meilleur investissement.
