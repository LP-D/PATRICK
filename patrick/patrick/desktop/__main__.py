"""`python -m patrick.desktop <commande>` : point d'entrée de l'application de bureau.

    launch [--no-update] [--no-ui]   ouvre PATRICK (ce que fait l'icône du bureau)
    stop                             arrête le serveur
    update [--check] [--pause]       met à jour (ou dit s'il y a du neuf)
    relaunch [--sync] [--update]     interne : relance demandée depuis la page Réglages
    pick-folder [--initial D]        interne : sélecteur de dossier natif, imprime le chemin choisi
    shortcuts                        (re)crée les raccourcis du bureau et du menu Démarrer
"""
from __future__ import annotations

import argparse
import json
import sys


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m patrick.desktop", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    launch = sub.add_parser("launch", help="ouvre PATRICK")
    launch.add_argument("--no-update", action="store_true", help="ne cherche pas de mise à jour")
    launch.add_argument("--no-ui", action="store_true", help="sans fenêtres natives (messages dans la console)")
    sub.add_parser("stop", help="arrête le serveur")
    upd = sub.add_parser("update", help="met à jour PATRICK")
    upd.add_argument("--check", action="store_true", help="dit seulement s'il y a une nouvelle version")
    upd.add_argument("--pause", action="store_true", help="attend une touche à la fin (fenêtre de commande)")
    relaunch = sub.add_parser("relaunch", help="relance le serveur (interne)")
    relaunch.add_argument("--sync", action="store_true")
    relaunch.add_argument("--update", action="store_true")
    relaunch.add_argument("--server-pid", type=int, default=None)
    pick = sub.add_parser("pick-folder", help="sélecteur de dossier (interne)")
    pick.add_argument("--initial", default=None)
    sub.add_parser("shortcuts", help="(re)crée les raccourcis")
    return parser


def _launch(*, no_update: bool, no_ui: bool) -> int:
    """Ouvre PATRICK. Sans console (`pythonw`), toute erreur est journalisée ET affichée : jamais d'échec muet."""
    from patrick.desktop import launcher, ui

    try:
        if no_ui:
            return launcher.run(ui.ConsoleReporter(), skip_update=no_update)
        try:
            reporter = ui.TkReporter()
        except Exception as exc:  # noqa: BLE001 -- tkinter absent / pas d'affichage : on continue sans fenêtres
            launcher.log(f"fenêtres natives indisponibles ({exc}) : démarrage sans assistant")
            return launcher.run(ui.ConsoleReporter(), skip_update=no_update)
        return reporter.run(lambda rep: launcher.run(rep, skip_update=no_update))
    except Exception as exc:  # noqa: BLE001
        import traceback

        launcher.log("erreur fatale du lanceur :\n" + traceback.format_exc())
        ui.notify(f"PATRICK n'a pas pu démarrer : {exc}\n\nJournal : {launcher.runtime.log_dir() / 'launcher.log'}",
                  error=True)
        return 1


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "launch":
        return _launch(no_update=args.no_update, no_ui=args.no_ui)
    if args.command == "stop":
        from patrick.desktop import launcher, ui

        stopped = launcher.stop()
        message = "PATRICK arrêté." if stopped else "Aucun serveur PATRICK en cours."
        if sys.stdout is None:          # lancé par le raccourci du menu Démarrer (pythonw : pas de console)
            ui.notify(message + "\n(Un entraînement lancé continue en arrière-plan.)")
        else:
            print(message)
        return 0
    if args.command == "update":
        from patrick.desktop import update

        result = update.check() if args.check else update.apply(progress=print)
        print(json.dumps(result, ensure_ascii=False, indent=1) if args.check else result["message"])
        if args.pause:
            input("Appuie sur Entrée pour fermer…")
        return 0 if result.get("status", result.get("state")) != "failed" else 1
    if args.command == "relaunch":
        from patrick.desktop import launcher

        return launcher.relaunch(do_sync=args.sync, do_update=args.update, server_pid=args.server_pid)
    if args.command == "pick-folder":
        from patrick.desktop import ui

        print(json.dumps({"folder": ui.pick_folder(args.initial)}))
        return 0
    if args.command == "shortcuts":
        from patrick.desktop import shortcuts

        return shortcuts.create()
    return 2


if __name__ == "__main__":
    sys.exit(main())
