# Python project template

Ce dépôt est le **template maître**, pas une application. Cookiecutter génère un
nouveau dépôt ; Cruft conserve le lien pour les mises à jour futures.

```bash
cd ~/projects
uvx cruft create ~/python-project-template  # ou l'URL Git du template
cd my-python-project
make init
make shell
make check
```

Cookiecutter reste utilisable directement :
`uvx cookiecutter <URL-ou-chemin-du-template>`.
Les questions couvrent le nom, slug, package, description, auteur, Python,
runtime de développement (Podman/Docker/aucun), CI et activation des notebooks,
de la documentation et le choix `coding_agent` (Codex par défaut) :

```text
1. codex  — OpenAI Codex uniquement
2. claude — Claude Code uniquement
3. both   — les deux CLI, au choix dans le même clone
4. custom — sandbox isolée sans harness préinstallé
5. none   — aucune infrastructure agent
```

Python 3.12 est le défaut minimum. Le nom de variable Cruft reste inchangé.
Les noms simples comme `Flood Extent` donnent `flood-extent` / `flood_extent` ;
les slugs complexes ou accentués doivent être ajustés à l’invite en ASCII.

Le projet produit utilise uv, uv_build, Ruff, mypy, pytest, pre-commit,
Jupytext et MkDocs Material. Le README généré expose les commandes usuelles ;
les détails et décisions sont versionnés dans `docs/` si activé.
Les composants désactivés sont retirés, ainsi que leurs groupes et cibles Make.

Developing the template :

```bash
cd ~/python-project-template
make setup
make check
make agent-check
make agent-login
make agent
```

Le maître dogfoode maintenant sa propre sandbox Podman rootless, par défaut
avec le profil `both`. L’agent développe **ce dépôt**, dans le clone indépendant
`.agent/workspace` ; aucun projet généré imbriqué ne sert de source de vérité.
`make agent-codex` et `make agent-claude` partagent ce clone. La configuration
locale `.env` choisit `AGENT_PROFILE` et `AGENT_DEFAULT_PROVIDER` ; `custom` est
aussi disponible. Le lifecycle, les ports et la récupération Git réutilisent
directement les sources du générateur. Après une modification des sources
partagées, `make agent-sync` synchronise les fichiers de build du maître.

Consultez le [guide de développement dans la sandbox](docs/agent.md) pour la
validation hôte, les logins séparés, le test fonctionnel commit/diff/test/apply,
les volumes persistants et la transition depuis Docker. Les tests runtime
Podman restent volontairement **sur l’hôte** : aucun socket moteur n’est monté
dans l’agent pour les exécuter. `make check` affiche leurs skips dans la sandbox.
Docker n’est pas requis pour ce workflow. Les fichiers bootstrap locaux sont
préservés jusqu’à validation manuelle ; ne les supprimez pas prématurément.
Les projets générés conservent leur choix de runtime dev Docker.

Générer une démonstration pour inspection et smoke tests :

```bash
make generate-default
make clean-generated  # suppression explicite de generated/ uniquement
```

La génération écrit dans `generated/` et refuse un dossier projet existant.
`generated/` est jetable, ignoré par Git et ne contient aucune source nécessaire
au template. Son nettoyage n'est pas implicite dans une autre commande.
Pour un vrai projet, lancez Cruft depuis le dossier parent souhaité :

```text
~/projects/
├── python-project-template/
└── my-python-project/
```

Ne placez pas vos projets permanents sous `python-project-template/generated/`.
Dans le projet créé, `make init` crée un `.git` indépendant, appelle setup,
installe pre-commit et crée le premier commit. L'identité Git doit être configurée
par l'utilisateur ; l'auteur du package n'est pas une identité Git automatique.
Un dépôt parent n'est jamais réinitialisé ou commité par cette commande.
Les exécutions suivantes ne créent pas de nouveau commit ; les changements
utilisateur d'un dépôt déjà commité sont préservés. `make setup` synchronise
seulement l'environnement et les hooks, sans initialiser Git ni commiter.

Modifiez les fichiers dans `{{cookiecutter.project_slug}}/`, les hooks dans
`hooks/`, les tests dans `tests/`. Le lock racine concerne les outils du
générateur ; chaque projet généré obtient son propre uv.lock. Si uv est absent
ou si le réseau échoue lors de la génération, `make setup` le crée ensuite.

La suite teste une matrice représentative des options, les entrées invalides,
les scripts shell, Jupytext, la configuration de sécurité, l’isolation Git et
le cherry-pick dans des dépôts temporaires. Elle exécute réellement setup,
checks, build et documentation d’un projet généré par défaut. Les tests de
conteneurs sont conditionnels à la disponibilité d’un moteur utilisable ;
un skip ne constitue pas une validation d'exécution.

La suite teste aussi `make init` sans dépôt, dans un dépôt parent, sans identité
Git et lors d'une deuxième exécution. Les tests purement Git isolent Podman ;
les tests runtime utilisent des ports hôte dynamiques et des projets Compose
uniques. Les valeurs ergonomiques de `.env.example` restent inchangées.

Depuis WSL, hors conteneur bootstrap, gardez le bootstrap actif s'il occupe
8000 et validez la suite :

```bash
cd ~/python-project-template
make check
```

Puis créez un projet indépendant dans un emplacement neuf :

```bash
mkdir -p ~/projects
cd ~/projects
cruft create ~/python-project-template
cd my-python-project
make init
make check
make agent-check
make agent-start
make agent-status
make agent-test
make agent-stop
```

Lancez ensuite `make agent-login` et `make agent` pour valider manuellement
l'authentification et l'interactivité de la CLI choisie.
La configuration Podman et les diagnostics sont documentés dans le guide
`docs/podman.md` des projets générés qui utilisent Podman. Ne montez pas le
socket hôte dans le bootstrap pour contourner une validation indisponible.

Les GitHub Actions et GitLab CI générées reprennent `make check`, `make build`
et le build documentaire. Pages nécessite l’activation du fournisseur côté
dépôt. Aucun déploiement ni push n’est effectué par le générateur.

Pour un projet créé via Cruft :

```bash
cruft check
cruft diff
cruft update
make check
```

Lisez les différences et résolvez les conflits avant de commiter la mise à jour.
Cookiecutter seul ne crée pas `.cruft.json` ; privilégiez Cruft dès la création.

Migration obligatoire des projets historiques avec `enable_agent` : Cookiecutter
ignore les anciennes variables supprimées, et Cruft ne convertit pas leur sens.
**Avant la première mise à jour vers ce template**, sauvegardez/commitez votre
travail puis choisissez explicitement la valeur correspondant à l'ancien contexte :

```bash
# ancien enable_agent=yes : conserver Codex
uvx cruft update --variables-to-update '{"coding_agent":"codex"}'
# ancien enable_agent=no : conserver l'absence d'agent
uvx cruft update --variables-to-update '{"coding_agent":"none"}'
```

Ne lancez pas une mise à jour sans ce choix sur un ancien contexte `no` : le
nouveau défaut serait Codex. La migration n'est pas transparente ; la suite
teste de vrais commits de templates avec l'ancien schéma et ces commandes.
Revoyez le diff proposé, les éventuels conflits et `.cruft.json`, puis exécutez
les checks. Après migration, `coding_agent` est enregistré et les mises à jour
suivantes utilisent normalement `cruft check`, `cruft diff` et `cruft update`.
Arrêtez/archivez une session `.agent/` avant de changer de provider ; un état
d'un autre provider est refusé. Les anciens états sans provider sont Codex.

La sandbox agent finale utilise toujours **Podman rootless** : clone Git
indépendant sans hardlinks, utilisateur non-root, aucun socket moteur ni HOME
hôte, credentials du provider dans un volume dédié et ports liés à localhost.
Le conteneur de développement humain peut utiliser Podman ou Docker et monte
son checkout. Les deux usages restent distincts. `make agent` vérifie le
runtime, exige un checkout propre, démarre le clone et ouvre la CLI choisie. L’agent
contrôle son workspace ; l’hôte contrôle la sandbox et récupère volontairement
les commits par `make agent-apply`. L’accès Internet sortant et la lecture du
contenu du clone restent permis ; ne fournissez pas de secrets dans le dépôt.
Les ports agent de `.env` sont des préférences : une collision sélectionne
automatiquement un port localhost libre, sans arrêter un autre projet. Les
ports effectifs sont conservés dans `.agent/state.json` et affichés par
`make agent-status`, puis réutilisés au redémarrage lorsqu'ils restent libres.

Avec `both`, les CLI partagent le conteneur, le clone et l'environnement Python,
mais leurs volumes d'authentification restent séparés. Définissez
`AGENT_DEFAULT_PROVIDER=codex` ou `claude` dans `.env`, ou utilisez directement
`make agent-codex`, `make agent-claude`, `make agent-login-codex` et
`make agent-login-claude`. Le template ne lance jamais les deux automatiquement ;
évitez les modifications/commits concurrents sur ce clone commun.

Avec `custom`, commencez par `make agent-check`, `make agent-start`, puis
`make agent-shell`. La sandbox contient l'outillage de développement, sans
harness IA. Le chemin durable recommandé consiste à éditer
`containers/agent-custom-install.sh` (no-op initial, exécuté non-root au build),
configurer `CUSTOM_AGENT_COMMAND` et éventuellement `CUSTOM_AGENT_ARGS` dans
`.env`, puis `make agent-rebuild` et `make agent`. Sans commande, `make agent`
démarre la sandbox et affiche une instruction claire pour la configurer.

Le build installe dans `/opt/agent-tools`, devant `.local/bin` dans le PATH,
pour qu'un volume utilisateur ancien ne masque pas les nouvelles versions.
Le prefix npm runtime est `.local` ; les volumes nommés `.local` et `.config`
préservent l'exploration/configuration mais ne couvrent pas tous les harnesses.
Ne montez jamais le HOME hôte pour persister un dossier de credentials spécifique.
Les arguments custom sont passés comme argv, sans eval ni shell hôte. Ne mettez
pas de token dans les arguments ou dans le script de build.

Lors d'un changement de profil Cruft, par exemple :

```bash
uvx cruft update --variables-to-update '{"coding_agent":"both"}'
```

un ancien état incompatible est refusé. `make agent-clean` peut arrêter/nettoyer
l'ancienne stack sans effacer ses volumes. Préservez tous les commits/changements
du clone avec `make agent-archive`, puis reconstruisez et démarrez la
nouvelle session. Les volumes Codex/Claude conservent leurs noms lors du passage
à both, donc leurs authentifications restent récupérables. Les gardes Git restent
actives : commitez la recette avant la première session. Si le HEAD principal
avance sans travail agent restant, le prochain `make agent` rafraîchit le clone.
Sinon, utilisez `make agent-rebase` ou `make agent-archive` après revue ;
`make agent-refresh` offre un refresh sûr explicite. Le HEAD principal n'est
jamais réaligné automatiquement.
La stack agent sélectionne automatiquement `podman-compose` (à installer sur
l'hôte) ; le dev container garde son choix de provider. Une erreur de session
systemd WSL déjà activée se traite d'abord par `wsl --shutdown` depuis Windows,
puis réouverture et nouveau diagnostic, avant toute modification système.

Pour chaque variante Codex et Claude, créez un projet séparé avec `uvx cruft create`,
choisissez le provider, puis `make init`, `make agent-check`, `make agent-login`,
`make agent`. Arrêtez/redémarrez, puis recréez avec `make agent-clean` suivi de
`make agent-start` : vérifiez manuellement que l'authentification persiste.
Les tests automatisés n'utilisent jamais de vraie connexion ; ils vérifient
une sentinelle dans le volume lorsque Podman est disponible.

`make shell` charge maintenant les RC Bash/Zsh et donc Oh My Zsh déjà installé
sur l'hôte. Aucun HOME n'est modifié et aucun installateur n'est lancé par cette
commande. Le PATH de l'environnement reste sans doublon après imbrication.
L'image dev fournit Oh My Zsh à un commit verrouillé ; l'image agent ne l'ajoute pas.
Validez manuellement votre prompt, alias, `echo "$VIRTUAL_ENV"` et `which python`,
puis `exit` pour revenir au shell parent. Voir le guide développement généré.

Références vérifiées lors de l’implémentation :

- [Backend uv_build](https://docs.astral.sh/uv/concepts/build-backend/)
- [Groupes uv](https://docs.astral.sh/uv/concepts/dependencies/)
- [Installation uv en CI GitHub](https://docs.astral.sh/uv/guides/integration/github/)
- [Codex CLI officiel](https://learn.chatgpt.com/docs/codex/cli)

Les versions critiques sont centralisées dans les arguments du Containerfile
(CODEX_VERSION ou CLAUDE_CODE_VERSION, Node partagé, OH_MY_ZSH_COMMIT pour dev).
Mettez à jour ces pins et reconstruisez pour changer de version. Les tags d’images système et
paquets apt ne sont pas immuables ; voir la documentation conteneurs générée
pour le durcissement par digests et la maintenance des versions.

Support : Linux et WSL2, bash et zsh. macOS : best effort initial.
Windows natif, PowerShell et cmd.exe : hors périmètre.

Les fichiers locaux `Dockerfile.dev` et `docker-compose.yaml` du bootstrap ne
font pas partie de l’architecture générée et ne sont pas versionnés par ce ticket.
