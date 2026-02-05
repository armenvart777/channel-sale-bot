import aiosqlite
from config import DB_PATH


class Database:
    def __init__(self):
        self.db: aiosqlite.Connection | None = None

    async def connect(self):
        self.db = await aiosqlite.connect(DB_PATH)
        self.db.row_factory = aiosqlite.Row
        await self.db.execute("PRAGMA journal_mode=WAL")
        await self._create_tables()

    async def close(self):
        if self.db:
            await self.db.close()

    async def _create_tables(self):
        await self.db.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                full_name TEXT,
                referrer_id INTEGER,
                referral_balance INTEGER DEFAULT 0,
                platform TEXT DEFAULT 'tg',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS subscriptions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                tariff_key TEXT NOT NULL,
                started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expires_at TIMESTAMP NOT NULL,
                is_active INTEGER DEFAULT 1,
                payment_id TEXT,
                platform TEXT DEFAULT 'tg',
                notified_3d INTEGER DEFAULT 0,
                notified_1d INTEGER DEFAULT 0,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            );

            CREATE TABLE IF NOT EXISTS payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                tariff_key TEXT NOT NULL,
                amount INTEGER NOT NULL,
                payment_id TEXT UNIQUE,
                status TEXT DEFAULT 'pending',
                promo_code TEXT,
                platform TEXT DEFAULT 'tg',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            );

            CREATE TABLE IF NOT EXISTS promo_codes (
                code TEXT PRIMARY KEY,
                discount_percent INTEGER NOT NULL,
                max_uses INTEGER DEFAULT 0,
                used_count INTEGER DEFAULT 0,
                is_active INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS referral_withdrawals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                amount INTEGER NOT NULL,
                card_info TEXT NOT NULL,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            );

            CREATE TABLE IF NOT EXISTS onboarding_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                step INTEGER UNIQUE NOT NULL,
                text TEXT NOT NULL,
                photo_id TEXT,
                video_id TEXT
            );

            CREATE TABLE IF NOT EXISTS preview_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sort_order INTEGER DEFAULT 0,
                text TEXT,
                photo_id TEXT,
                video_id TEXT
            );

            CREATE TABLE IF NOT EXISTS bot_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_subs_user_active
                ON subscriptions(user_id, is_active);
            CREATE INDEX IF NOT EXISTS idx_subs_expires
                ON subscriptions(is_active, expires_at);
            CREATE INDEX IF NOT EXISTS idx_users_referrer
                ON users(referrer_id);
        """)
        await self.db.commit()

    # ── Users ──

    async def get_user(self, user_id: int) -> dict | None:
        cur = await self.db.execute(
            "SELECT * FROM users WHERE user_id = ?", (user_id,)
        )
        row = await cur.fetchone()
        return dict(row) if row else None

    async def add_user(self, user_id: int, username: str, full_name: str,
                       referrer_id: int | None = None,
                       platform: str = "tg"):
        """Insert new user or update username/full_name if exists."""
        await self.db.execute(
            """INSERT INTO users (user_id, username, full_name, referrer_id, platform)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(user_id) DO UPDATE SET
                   username = excluded.username,
                   full_name = excluded.full_name,
                   referrer_id = CASE WHEN users.referrer_id IS NULL THEN excluded.referrer_id ELSE users.referrer_id END""",
            (user_id, username, full_name, referrer_id, platform),
        )
        await self.db.commit()

    async def get_user_count(self) -> int:
        cur = await self.db.execute("SELECT COUNT(*) FROM users")
        return (await cur.fetchone())[0]

    async def get_all_user_ids(self, platform: str | None = None) -> list[int]:
        if platform:
            cur = await self.db.execute(
                "SELECT user_id FROM users WHERE platform = ?", (platform,)
            )
        else:
            cur = await self.db.execute("SELECT user_id FROM users")
        return [row[0] for row in await cur.fetchall()]

    async def get_buyers(self, platform: str | None = None) -> list[int]:
        if platform:
            cur = await self.db.execute(
                """SELECT DISTINCT s.user_id FROM subscriptions s
                   JOIN users u ON s.user_id = u.user_id
                   WHERE s.is_active = 1 AND u.platform = ?""",
                (platform,),
            )
        else:
            cur = await self.db.execute(
                "SELECT DISTINCT user_id FROM subscriptions WHERE is_active = 1"
            )
        return [row[0] for row in await cur.fetchall()]

    async def get_non_buyers(self, platform: str | None = None) -> list[int]:
        if platform:
            cur = await self.db.execute(
                """SELECT user_id FROM users
                   WHERE platform = ? AND user_id NOT IN (
                       SELECT DISTINCT user_id FROM subscriptions WHERE is_active = 1
                   )""",
                (platform,),
            )
        else:
            cur = await self.db.execute(
                """SELECT user_id FROM users
                   WHERE user_id NOT IN (
                       SELECT DISTINCT user_id FROM subscriptions WHERE is_active = 1
                   )"""
            )
        return [row[0] for row in await cur.fetchall()]

    # ── Subscriptions ──

    async def get_active_subscription(self, user_id: int) -> dict | None:
        cur = await self.db.execute(
            """SELECT * FROM subscriptions
               WHERE user_id = ? AND is_active = 1
               ORDER BY expires_at DESC LIMIT 1""",
            (user_id,),
        )
        row = await cur.fetchone()
        return dict(row) if row else None

    async def add_subscription(self, user_id: int, tariff_key: str,
                               expires_at: str, payment_id: str,
                               platform: str = "tg"):
        await self.db.execute(
            """INSERT INTO subscriptions
               (user_id, tariff_key, expires_at, payment_id, platform)
               VALUES (?, ?, ?, ?, ?)""",
            (user_id, tariff_key, expires_at, payment_id, platform),
        )
        await self.db.commit()

    async def extend_or_create_subscription(self, user_id: int, tariff_key: str,
                                            days: int, payment_id: str,
                                            platform: str = "tg") -> str:
        """Atomically deactivate old sub and create new one. Returns expires_at."""
        from datetime import datetime, timedelta, timezone

        now = datetime.now(timezone.utc)

        existing = await self.get_active_subscription(user_id)
        if existing:
            base = datetime.fromisoformat(existing["expires_at"])
            if base.tzinfo is None:
                base = base.replace(tzinfo=timezone.utc)
            if base < now:
                base = now
            expires_at = base + timedelta(days=days)
            # Single transaction: deactivate old + create new
            await self.db.execute(
                "UPDATE subscriptions SET is_active = 0 WHERE id = ?",
                (existing["id"],),
            )
        else:
            expires_at = now + timedelta(days=days)

        await self.db.execute(
            """INSERT INTO subscriptions
               (user_id, tariff_key, expires_at, payment_id, platform)
               VALUES (?, ?, ?, ?, ?)""",
            (user_id, tariff_key, expires_at.strftime("%Y-%m-%dT%H:%M:%S"), payment_id, platform),
        )
        await self.db.commit()
        return expires_at.strftime("%Y-%m-%dT%H:%M:%S")

    async def deactivate_subscription(self, sub_id: int):
        await self.db.execute(
            "UPDATE subscriptions SET is_active = 0 WHERE id = ?", (sub_id,)
        )
        await self.db.commit()

    async def get_expiring_subscriptions(self, days: int,
                                         platform: str | None = None) -> list[dict]:
        notified_col = "notified_3d" if days == 3 else "notified_1d"
        if platform:
            cur = await self.db.execute(
                f"""SELECT * FROM subscriptions
                   WHERE is_active = 1 AND platform = ?
                   AND {notified_col} = 0
                   AND date(expires_at) = date('now', '+' || ? || ' days')""",
                (platform, days),
            )
        else:
            cur = await self.db.execute(
                f"""SELECT * FROM subscriptions
                   WHERE is_active = 1
                   AND {notified_col} = 0
                   AND date(expires_at) = date('now', '+' || ? || ' days')""",
                (days,),
            )
        return [dict(row) for row in await cur.fetchall()]

    async def mark_notified(self, sub_id: int, days: int):
        col = "notified_3d" if days == 3 else "notified_1d"
        await self.db.execute(
            f"UPDATE subscriptions SET {col} = 1 WHERE id = ?", (sub_id,)
        )
        await self.db.commit()

    async def get_expired_subscriptions(self,
                                        platform: str | None = None) -> list[dict]:
        if platform:
            cur = await self.db.execute(
                """SELECT * FROM subscriptions
                   WHERE is_active = 1 AND platform = ?
                   AND datetime(expires_at) <= datetime('now')""",
                (platform,),
            )
        else:
            cur = await self.db.execute(
                """SELECT * FROM subscriptions
                   WHERE is_active = 1
                   AND datetime(expires_at) <= datetime('now')"""
            )
        return [dict(row) for row in await cur.fetchall()]

    # ── Payments ──

    async def create_payment(self, user_id: int, tariff_key: str,
                             amount: int, payment_id: str,
                             promo_code: str | None = None,
                             platform: str = "tg"):
        await self.db.execute(
            """INSERT INTO payments
               (user_id, tariff_key, amount, payment_id, promo_code, platform)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (user_id, tariff_key, amount, payment_id, promo_code, platform),
        )
        await self.db.commit()

    async def claim_payment(self, payment_id: str) -> dict | None:
        """Atomically mark payment as succeeded. Returns payment dict or None
        if already claimed (race-safe)."""
        cur = await self.db.execute(
            """UPDATE payments SET status = 'succeeded'
               WHERE payment_id = ? AND status = 'pending'
               RETURNING *""",
            (payment_id,),
        )
        row = await cur.fetchone()
        await self.db.commit()
        return dict(row) if row else None

    async def get_payment(self, payment_id: str) -> dict | None:
        cur = await self.db.execute(
            "SELECT * FROM payments WHERE payment_id = ?", (payment_id,)
        )
        row = await cur.fetchone()
        return dict(row) if row else None

    async def get_total_revenue(self) -> int:
        cur = await self.db.execute(
            "SELECT COALESCE(SUM(amount), 0) FROM payments WHERE status = 'succeeded'"
        )
        return (await cur.fetchone())[0]

    async def get_payments_count(self) -> int:
        cur = await self.db.execute(
            "SELECT COUNT(*) FROM payments WHERE status = 'succeeded'"
        )
        return (await cur.fetchone())[0]

    # ── Promo codes ──

    async def get_promo(self, code: str) -> dict | None:
        cur = await self.db.execute(
            "SELECT * FROM promo_codes WHERE code = ? AND is_active = 1",
            (code.upper(),),
        )
        row = await cur.fetchone()
        return dict(row) if row else None

    async def create_promo(self, code: str, discount_percent: int,
                           max_uses: int = 0):
        await self.db.execute(
            """INSERT INTO promo_codes (code, discount_percent, max_uses)
               VALUES (?, ?, ?)""",
            (code.upper(), discount_percent, max_uses),
        )
        await self.db.commit()

    async def use_promo(self, code: str) -> bool:
        """Atomically increment usage if within limits. Returns True if consumed."""
        cur = await self.db.execute(
            """UPDATE promo_codes SET used_count = used_count + 1
               WHERE code = ? AND is_active = 1
               AND (max_uses = 0 OR used_count < max_uses)""",
            (code.upper(),),
        )
        await self.db.commit()
        return cur.rowcount > 0

    async def get_all_promos(self) -> list[dict]:
        cur = await self.db.execute("SELECT * FROM promo_codes")
        return [dict(row) for row in await cur.fetchall()]

    async def delete_promo(self, code: str):
        await self.db.execute(
            "UPDATE promo_codes SET is_active = 0 WHERE code = ?",
            (code.upper(),),
        )
        await self.db.commit()

    # ── Referral ──

    async def get_referral_count(self, user_id: int) -> int:
        cur = await self.db.execute(
            "SELECT COUNT(*) FROM users WHERE referrer_id = ?", (user_id,)
        )
        return (await cur.fetchone())[0]

    async def get_referral_earnings(self, user_id: int) -> int:
        user = await self.get_user(user_id)
        return user["referral_balance"] if user else 0

    async def add_referral_bonus(self, user_id: int, amount: int):
        await self.db.execute(
            "UPDATE users SET referral_balance = referral_balance + ? WHERE user_id = ?",
            (amount, user_id),
        )
        await self.db.commit()

    async def create_withdrawal(self, user_id: int, amount: int,
                                card_info: str) -> bool:
        """Create withdrawal with atomic balance check. Returns False if insufficient."""
        cur = await self.db.execute(
            """UPDATE users SET referral_balance = referral_balance - ?
               WHERE user_id = ? AND referral_balance >= ?""",
            (amount, user_id, amount),
        )
        if cur.rowcount == 0:
            await self.db.rollback()
            return False
        await self.db.execute(
            """INSERT INTO referral_withdrawals (user_id, amount, card_info)
               VALUES (?, ?, ?)""",
            (user_id, amount, card_info),
        )
        await self.db.commit()
        return True

    async def get_pending_withdrawals(self) -> list[dict]:
        cur = await self.db.execute(
            """SELECT w.*, u.username, u.full_name
               FROM referral_withdrawals w
               JOIN users u ON w.user_id = u.user_id
               WHERE w.status = 'pending'"""
        )
        return [dict(row) for row in await cur.fetchall()]

    async def complete_withdrawal(self, withdrawal_id: int):
        await self.db.execute(
            "UPDATE referral_withdrawals SET status = 'done' WHERE id = ?",
            (withdrawal_id,),
        )
        await self.db.commit()

    async def reject_withdrawal(self, withdrawal_id: int):
        """Reject withdrawal and return money to user's balance."""
        cur = await self.db.execute(
            "SELECT user_id, amount FROM referral_withdrawals WHERE id = ? AND status = 'pending'",
            (withdrawal_id,),
        )
        row = await cur.fetchone()
        if not row:
            return
        await self.db.execute(
            "UPDATE referral_withdrawals SET status = 'rejected' WHERE id = ?",
            (withdrawal_id,),
        )
        await self.db.execute(
            "UPDATE users SET referral_balance = referral_balance + ? WHERE user_id = ?",
            (row["amount"], row["user_id"]),
        )
        await self.db.commit()

    # ── Onboarding ──

    async def get_onboarding_steps(self) -> list[dict]:
        cur = await self.db.execute(
            "SELECT * FROM onboarding_messages ORDER BY step"
        )
        return [dict(row) for row in await cur.fetchall()]

    async def set_onboarding_step(self, step: int, text: str,
                                  photo_id: str | None = None,
                                  video_id: str | None = None):
        await self.db.execute(
            """INSERT OR REPLACE INTO onboarding_messages (step, text, photo_id, video_id)
               VALUES (?, ?, ?, ?)""",
            (step, text, photo_id, video_id),
        )
        await self.db.commit()

    async def delete_onboarding_step(self, step: int):
        await self.db.execute(
            "DELETE FROM onboarding_messages WHERE step = ?", (step,)
        )
        await self.db.commit()

    # ── Preview ──

    async def get_preview_messages(self) -> list[dict]:
        cur = await self.db.execute(
            "SELECT * FROM preview_messages ORDER BY sort_order"
        )
        return [dict(row) for row in await cur.fetchall()]

    async def add_preview_message(self, text: str | None, photo_id: str | None,
                                  video_id: str | None, sort_order: int = 0):
        await self.db.execute(
            """INSERT INTO preview_messages (text, photo_id, video_id, sort_order)
               VALUES (?, ?, ?, ?)""",
            (text, photo_id, video_id, sort_order),
        )
        await self.db.commit()

    async def clear_preview(self):
        await self.db.execute("DELETE FROM preview_messages")
        await self.db.commit()

    # ── Settings ──

    async def get_setting(self, key: str) -> str | None:
        cur = await self.db.execute(
            "SELECT value FROM bot_settings WHERE key = ?", (key,)
        )
        row = await cur.fetchone()
        return row["value"] if row else None

    async def set_setting(self, key: str, value: str):
        await self.db.execute(
            "INSERT OR REPLACE INTO bot_settings (key, value) VALUES (?, ?)",
            (key, value),
        )
        await self.db.commit()

    # ── Stats ──

    async def get_stats(self) -> dict:
        total_users = await self.get_user_count()
        active_subs = await self.db.execute(
            "SELECT COUNT(*) FROM subscriptions WHERE is_active = 1"
        )
        active_count = (await active_subs.fetchone())[0]
        revenue = await self.get_total_revenue()
        payments = await self.get_payments_count()
        return {
            "total_users": total_users,
            "active_subscriptions": active_count,
            "total_revenue": revenue,
            "total_payments": payments,
        }


db = Database()
