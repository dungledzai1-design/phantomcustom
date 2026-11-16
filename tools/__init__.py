"""Tool registry for PhantomCustom."""
from . import discord_spam, zalo_spam, fb_mess, fb_nhay, zalo_multi

TOOLS = {
    "treodis": discord_spam.run_treodis,
    "nhaydiscord": discord_spam.run_nhaydiscord,
    "treozalo": zalo_spam.run,
    "treomess": fb_mess.run,
    "nhaymess": fb_nhay.run,
    "zalomulti": zalo_multi.run,
}

TOOL_META = {
    "treodis": {
        "name": "Treo Discord",
        "icon": "discord",
        "desc": "Spam nhiều token vào nhiều channel Discord, delay tuỳ chỉnh.",
        "fields": ["tokens", "channels", "message", "delay"],
    },
    "nhaydiscord": {
        "name": "Nhây Discord",
        "icon": "discord",
        "desc": "Nhây liên tục bằng token vào UID channel Discord.",
        "fields": ["token", "channel", "message", "delay"],
    },
    "treozalo": {
        "name": "Treo Zalo",
        "icon": "zalo",
        "desc": "Chỉ cần IMEI + session cookie là chạy. Text/ảnh/video, mention, style, TTL.",
        "fields": ["imei", "cookies", "groups", "message",
                   "delay", "ttl", "colors", "media_type", "media_source"],
    },
    "treomess": {
        "name": "Treo Messenger",
        "icon": "messenger",
        "desc": "Treo Messenger nhiều cookie vào nhiều box, đa tài khoản luân phiên.",
        "fields": ["cookies", "threads", "messages", "delay"],
    },
    "nhaymess": {
        "name": "Nhây Messenger",
        "icon": "messenger",
        "desc": "Fake typing MQTT + tag mention thành viên trong box.",
        "fields": ["cookie", "thread", "members", "message", "delay", "typing"],
    },
    "zalomulti": {
        "name": "Zalo Đa Năng",
        "icon": "zalo",
        "desc": "Chỉ cần IMEI + cookie. 10 chế độ: nhaytag, treongon, spamcall, treoanh, đổi tên/avatar, sticker, voice, card, join.",
        "fields": ["imei", "cookies", "mode", "groups",
                   "message", "messages", "delay_min", "delay_max", "tag_multiple",
                   "tag_random", "members", "repeat_count", "image_folder",
                   "sticker_count", "join_link"],
    },
}
