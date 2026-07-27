"""
One-time migration: update fake @newinventory.customer emails to
inv.<n>.<firstname>@foodstuff.store format.

Run via:
    heroku run python migrate_emails.py --app <newinventory-app>
Or locally:
    DATABASE_URL=... python migrate_emails.py
"""
import os
import re
import asyncio
import asyncpg


def _clean_name(name: str) -> str:
    first = (name or "").strip().split()[0] if (name or "").strip() else "customer"
    return re.sub(r"[^a-z0-9]", "", first.lower()) or "customer"


async def main():
    url = os.environ["DATABASE_URL"].replace("postgres://", "postgresql://", 1)
    conn = await asyncpg.connect(url)

    rows = await conn.fetch(
        "SELECT id, customer_name, email FROM customers WHERE email LIKE '%@newinventory.customer'"
    )

    if not rows:
        print("No fake emails found — nothing to migrate.")
        await conn.close()
        return

    # Fetch existing emails that are NOT fake so we can detect conflicts
    existing = {
        r["email"]
        for r in await conn.fetch(
            "SELECT email FROM customers WHERE email NOT LIKE '%@newinventory.customer' AND email IS NOT NULL"
        )
    }

    print(f"Found {len(rows)} customer(s) to update:\n")
    updates = []
    seen_in_batch: set[str] = set()
    for r in rows:
        local = r["email"].split("@")[0]
        first = _clean_name(r["customer_name"])
        candidate = f"{local}.{first}@foodstuff.store"

        # Resolve collisions: append customer id number until unique
        if candidate in existing or candidate in seen_in_batch:
            # extract trailing digits from local part (e.g. "inv.24" → "24")
            num = re.sub(r"[^0-9]", "", local) or str(r["id"])
            candidate = f"{local}.{first}{num}@foodstuff.store"

        new_email = candidate
        seen_in_batch.add(new_email)
        print(f"  [{r['id']:>4}] {r['email']:<35} → {new_email}")
        updates.append((new_email, r["id"]))

    # Final sanity check: flag any remaining duplicates within the batch
    new_emails = [u[0] for u in updates]
    if len(new_emails) != len(set(new_emails)):
        from collections import Counter
        dupes = [e for e, c in Counter(new_emails).items() if c > 1]
        print(f"\nERROR: Duplicate new emails still present after dedup: {dupes}")
        print("Aborted — resolve manually.")
        await conn.close()
        return

    answer = input("\nApply these changes? [y/N] ").strip().lower()
    if answer != "y":
        print("Aborted.")
        await conn.close()
        return

    async with conn.transaction():
        for new_email, cid in updates:
            await conn.execute(
                "UPDATE customers SET email = $1 WHERE id = $2", new_email, cid
            )

    print(f"\nUpdated {len(updates)} email(s).")
    await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
