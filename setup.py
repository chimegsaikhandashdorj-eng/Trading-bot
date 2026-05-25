"""
Тохиргооны туслах скрипт — .env файл үүсгэж API холболт шалгана
"""
import shutil
from pathlib import Path


def setup():
    print("\n" + "="*55)
    print("  Trading Bot - Тохиргоо")
    print("="*55)

    # .env файл үүсгэх
    env_path = Path(".env")
    if not env_path.exists():
        shutil.copy(".env.example", ".env")
        print("✅ .env файл үүсгэгдлээ")
    else:
        print("ℹ️  .env файл аль хэдийн байна")

    print("""
📌 ДАРААХ АЛХМУУДЫГ ХИЙНЭ ҮҮ:

1. .env файлыг нээж API түлхүүрүүдийг оруулна уу:

   [Binance]
   → binance.com → Account → API Management → Create API Key
   → BINANCE_API_KEY болон BINANCE_SECRET_KEY-г оруулна

   [X.com (Twitter)]
   → developer.twitter.com → Projects & Apps → Create App
   → X_BEARER_TOKEN, X_API_KEY, X_API_SECRET гэх мэт

   [Telegram Bot]
   → Telegram дээр @BotFather-тай ярилцаж Bot үүсгэнэ
   → /newbot командыг ашигла → TELEGRAM_BOT_TOKEN авна
   → @userinfobot-д мессеж илгээж TELEGRAM_CHAT_ID авна

   [MetaTrader 5 - motcapital.com]
   → MT5 программыг нэвтэрч MT5_LOGIN, MT5_PASSWORD, MT5_SERVER оруулна

2. Library суулгах:
   pip install -r requirements.txt

3. Backtest хийх (эхлэхийн өмнө шалгаарай):
   python backtest.py --symbol BTC/USDT --days 30

4. Bot ажиллуулах:
   python main.py

⚠️  АНХААРУУЛГА: Бодит мөнгөгөөр арилжаа хийхийн өмнө
   заавал paper trading / backtest-ийг хийгээрэй!
""")


if __name__ == "__main__":
    setup()
