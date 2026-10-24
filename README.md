# Python project template

Ce dépôt est le **template maître**, pas une application. Cookiecutter génère un
nouveau dépôt ; Cruft conserve le lien pour les mises à jour futures.

```bash
uv tool install cruft
cruft create <URL-ou-chemin-Git-du-template>
cd my-python-project
make setup
make shell
make check
```

Cookiecutter reste utilisable directement :
`uvx cookiecutter <URL-ou-chemin-du-template>`.
Les questions couvrent le nom, slug, package, description, auteur, Python,
runtime de développement (Podman/Docker/aucun), CI et activation des notebooks,
de la documentation et de l’agent. Python 3.12 est le défaut minimum.
Les noms simples comme `Flood Extent` donnent `flood-extent` / `flood_extent` ;
les slugs complexes ou accentués doivent être ajustés à l’invite en ASCII.

Le projet produit utilise uv, uv_build, Ruff, mypy, pytest, pre-commit,
Jupytext et MkDocs Material. Le README généré expose les commandes usuelles ;
les détails et décisions sont versionnés dans `docs/` si activé.
Les composants désactivés sont retirés, ainsi que leurs groupes et cibles Make.

Développer le template :

```bash
uv sync
make check
make generate-default
```

Le dernier appel écrit dans `generated/` et refuse un dossier projet existant.
Modifiez les fichiers dans `{{cookiecutter.project_slug}}/`, les hooks dans
`hooks/`, les tests dans `tests/`. Le lock racine concerne les outils du
générateur ; chaque projet généré obtient son propre uv.lock. Si uv est absent
ou si le réseau échoue lors de la génération, `make setup` le crée ensuite.

La suite teste une matrice représentative des options, les entrées invalides,
les scripts shell, Jupytext, la configuration de sécurité, l’isolation Git et
le cherry-pick dans des dépôts temporaires. Elle exécute réellement setup,
checks, build et documentation d’un projet généré par défaut. Les tests de
conteneurs sont conditionnels à la disponibilité d’un moteur utilisable ;
un skip ne constitue pas une validation d’exécution.

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

La sandbox agent finale utilise toujours **Podman rootless** : clone Git
indépendant sans hardlinks, utilisateur non-root, aucun socket moteur ni HOME
hôte, credentials Codex dans un volume dédié et ports liés à localhost.
Le conteneur de développement humain peut utiliser Podman ou Docker et monte
son checkout. Les deux usages restent distincts. `make agent` vérifie le
runtime, exige un checkout propre, démarre le clone et ouvre Codex. L’agent
contrôle son workspace ; l’hôte contrôle la sandbox et récupère volontairement
les commits par `make agent-apply`. L’accès Internet sortant et la lecture du
contenu du clone restent permis ; ne fournissez pas de secrets dans le dépôt.

Références vérifiées lors de l’implémentation :

- [Backend uv_build](https://docs.astral.sh/uv/concepts/build-backend/)
- [Groupes uv](https://docs.astral.sh/uv/concepts/dependencies/)
- [Installation uv en CI GitHub](https://docs.astral.sh/uv/guides/integration/github/)
- [Codex CLI officiel](https://learn.chatgpt.com/docs/codex/cli)

Versions critiques : uv/uv_build 0.13.5, package officiel `@openai/codex` 0.164.0
(version stable vérifiée dans le registre npm). Les tags d’images système et
paquets apt ne sont pas immuables ; voir la documentation conteneurs générée
pour le durcissement par digests et la maintenance des versions.

Support : Linux et WSL2, bash et zsh. macOS : best effort initial.
Windows natif, PowerShell et cmd.exe : hors périmètre.

Les fichiers locaux `Dockerfile.dev` et `docker-compose.yaml` du bootstrap ne
font pas partie de l’architecture générée et ne sont pas versionnés par ce ticket.
