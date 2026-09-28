import os
import sqlite3

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatPermissions
from telegram.ext import ApplicationBuilder, CommandHandler, ChatMemberHandler, ContextTypes


BOT_TOKEN = os.environ["BOT_TOKEN"]

# Agar tumhara channel username @AajKiKhabarDaily hai to ise aise hi rehne do.
CHANNEL = "@AajKiKhabarDaily"

DB = "referrals.db"


def db():
    conn = sqlite3.connect(DB)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            invite_link TEXT,
            referrals INTEGER DEFAULT 0,
            unlocked INTEGER DEFAULT 0
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS referred (
            new_user_id INTEGER PRIMARY KEY,
            referrer_id INTEGER
        )
    """)

    conn.commit()
    return conn


def locked_permissions():
    return ChatPermissions(
        can_send_messages=False,
        can_send_audios=False,
        can_send_documents=False,
        can_send_photos=False,
        can_send_videos=False,
        can_send_video_notes=False,
        can_send_voice_notes=False,
        can_send_polls=False,
        can_send_other_messages=False,
        can_add_web_page_previews=False,
        can_invite_users=False,
        can_pin_messages=False,
    )


def unlocked_permissions():
    return ChatPermissions.all_permissions()


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    conn = db()

    row = conn.execute(
        "SELECT invite_link, referrals, unlocked FROM users WHERE user_id=?",
        (user.id,)
    ).fetchone()

    if row is None:
        invite = await context.bot.create_chat_invite_link(
            chat_id=CHANNEL,
            name=f"ref_{user.id}"
        )

        conn.execute(
            "INSERT INTO users(user_id, invite_link) VALUES (?, ?)",
            (user.id, invite.invite_link)
        )

        conn.commit()

        referral_link = invite.invite_link
        referrals = 0
        unlocked = 0

    else:
        referral_link, referrals, unlocked = row

    conn.close()

    if unlocked:
        await update.message.reply_text(
            "✅ आपका referral पूरा हो चुका है।\n\n"
            "🔓 अब आप discussion group में message कर सकते हैं।"
        )
        return

    keyboard = [[
        InlineKeyboardButton(
            "🔗 मेरा Referral Link",
            url=referral_link
        )
    ]]

    await update.message.reply_text(
        "🔒 आपका group messaging अभी locked है।\n\n"
        "आपको केवल 1 नया member अपने referral link से "
        "channel में join करवाना है।\n\n"
        "1️⃣ अपना referral link भेजें\n"
        "2️⃣ नया व्यक्ति उस link से channel join करे\n"
        "3️⃣ Referral पूरा होते ही group में messaging unlock हो जाएगी।\n\n"
        f"Referral: {referrals}/1",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def channel_member_update(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    cm = update.chat_member

    if not cm:
        return

    old_status = cm.old_chat_member.status
    new_status = cm.new_chat_member.status

    if new_status not in ("member", "administrator"):
        return

    if old_status in ("member", "administrator"):
        return

    if not cm.invite_link:
        return

    used_link = cm.invite_link.invite_link
    new_user_id = cm.new_chat_member.user.id

    conn = db()

    row = conn.execute(
        "SELECT user_id FROM users WHERE invite_link=?",
        (used_link,)
    ).fetchone()

    if not row:
        conn.close()
        return

    referrer_id = row[0]

    if referrer_id == new_user_id:
        conn.close()
        return

    already = conn.execute(
        "SELECT 1 FROM referred WHERE new_user_id=?",
        (new_user_id,)
    ).fetchone()

    if already:
        conn.close()
        return

    conn.execute(
        "INSERT INTO referred(new_user_id, referrer_id) VALUES (?, ?)",
        (new_user_id, referrer_id)
    )

    conn.execute(
        "UPDATE users SET referrals=referrals+1, unlocked=1 WHERE user_id=?",
        (referrer_id,)
    )

    conn.commit()
    conn.close()

    # Linked discussion group automatically find करें
    try:
        channel_info = await context.bot.get_chat(CHANNEL)
        group_id = channel_info.linked_chat_id

        if group_id:
            await context.bot.restrict_chat_member(
                chat_id=group_id,
                user_id=referrer_id,
                permissions=unlocked_permissions()
            )
    except Exception as e:
        print("Unlock error:", e)

    try:
        await context.bot.send_message(
            referrer_id,
            "🎉 Referral सफल हो गया!\n\n"
            "✅ 1 नया member आपके referral link से channel में आया है।\n"
            "🔓 अब discussion group में आपका messaging unlock हो गया है।"
        )
    except Exception:
        pass


async def group_member_update(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    cm = update.chat_member

    if not cm:
        return

    new_member = cm.new_chat_member

    if new_member.status != "member":
        return

    user_id = new_member.user.id
    group_id = update.effective_chat.id

    try:
        admins = await context.bot.get_chat_administrators(group_id)
        admin_ids = {a.user.id for a in admins}

        if user_id in admin_ids:
            return
    except Exception:
        pass

    conn = db()

    row = conn.execute(
        "SELECT unlocked FROM users WHERE user_id=?",
        (user_id,)
    ).fetchone()

    conn.close()

    if row and row[0] == 1:
        return

    try:
        await context.bot.restrict_chat_member(
            chat_id=group_id,
            user_id=user_id,
            permissions=locked_permissions()
        )
    except Exception as e:
        print("Restriction error:", e)


def main():
    app = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .build()
    )

    app.add_handler(
        CommandHandler("start", start)
    )

    app.add_handler(
        ChatMemberHandler(
            channel_member_update,
            ChatMemberHandler.CHAT_MEMBER
        )
    )

    app.add_handler(
        ChatMemberHandler(
            group_member_update,
            ChatMemberHandler.CHAT_MEMBER
        )
    )

    print("Referral bot is running...")

    app.run_polling(
        allowed_updates=["message", "chat_member"]
    )


if __name__ == "__main__":
    main()
