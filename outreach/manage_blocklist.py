import argparse

from outreach.config import load_config, save_config


def main():
    parser = argparse.ArgumentParser(description="Manage the permanent send blocklist.")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list")

    p = sub.add_parser("block-domain")
    p.add_argument("domain")
    p = sub.add_parser("unblock-domain")
    p.add_argument("domain")
    p = sub.add_parser("block-email")
    p.add_argument("email")
    p = sub.add_parser("unblock-email")
    p.add_argument("email")

    args = parser.parse_args()
    cfg = load_config()
    cfg.setdefault("disallowed_domains", [])
    cfg.setdefault("disallowed_emails", [])

    if args.command == "list":
        print("Blocked domains:", cfg["disallowed_domains"] or "(none)")
        print("Blocked emails:", cfg["disallowed_emails"] or "(none)")
        return

    if args.command == "block-domain":
        domain = args.domain.lower().strip()
        if domain not in cfg["disallowed_domains"]:
            cfg["disallowed_domains"].append(domain)
    elif args.command == "unblock-domain":
        domain = args.domain.lower().strip()
        if domain in cfg["disallowed_domains"]:
            cfg["disallowed_domains"].remove(domain)
    elif args.command == "block-email":
        email = args.email.lower().strip()
        if email not in cfg["disallowed_emails"]:
            cfg["disallowed_emails"].append(email)
    elif args.command == "unblock-email":
        email = args.email.lower().strip()
        if email in cfg["disallowed_emails"]:
            cfg["disallowed_emails"].remove(email)

    save_config(cfg)
    print("Updated.")


if __name__ == "__main__":
    main()
