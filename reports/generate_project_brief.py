from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.patches import Patch, Rectangle


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "reports" / "trading_scanner_project_brief.pdf"

INK = "#18332F"
MUTED = "#60736F"
PAPER = "#F5F7F3"
WHITE = "#FFFFFF"
TEAL = "#147D72"
GREEN = "#62A47A"
AMBER = "#D0943E"
RED = "#C65B58"
BLUE = "#547F9D"
PALE = "#E6EEEA"
GRID = "#D8E1DC"


def add_text(fig, x, y, text, size=9, color=INK, weight="normal", **kwargs):
    family = kwargs.pop("family", "DejaVu Sans")
    fig.text(x, y, text, fontsize=size, color=color, weight=weight,
             family=family, **kwargs)


def add_box(fig, x, y, width, height, color=WHITE, edge=GRID, radius=0.012):
    fig.patches.append(Rectangle(
        (x, y), width, height, transform=fig.transFigure,
        facecolor=color, edgecolor=edge, linewidth=0.7,
        joinstyle="round", zorder=-1,
    ))


def new_page():
    fig = plt.figure(figsize=(8.27, 11.69), facecolor=PAPER)
    fig.add_artist(Rectangle(
        (0, 0.985), 1, 0.015, transform=fig.transFigure,
        facecolor=TEAL, edgecolor="none",
    ))
    add_text(fig, 0.07, 0.963, "PROJECT BRIEF", 7.5, MUTED, "bold")
    add_text(fig, 0.93, 0.963, "30 SEP 2026", 7.5, MUTED, "bold",
             ha="right")
    return fig


def page_one(pdf):
    fig = new_page()
    add_text(fig, 0.07, 0.914,
             "SOLID XAU/USD SCAN AND ALERT RICHSCHEME 001", 17.5, INK, "bold")
    add_text(fig, 0.07, 0.884,
             "What works today, what the evidence says, and what to do next.",
             10.5, MUTED)

    add_box(fig, 0.07, 0.792, 0.86, 0.068, color=INK, edge=INK)
    add_text(fig, 0.095, 0.828,
             "Signals work. Signal confidence is not yet proven.",
             15, WHITE, "bold", va="center")

    metrics = [
        ("54.5%", "resolved-only hit rate", "66 TP1 / 121 resolved"),
        ("+0.64R", "mean on resolved sample", "Replay-reported average"),
        ("37", "automated tests passing", "Engineering, not strategy proof"),
    ]
    card_width = 0.27
    for index, (value, label, note) in enumerate(metrics):
        x = 0.07 + index * 0.295
        add_box(fig, x, 0.687, card_width, 0.083)
        add_text(fig, x + 0.015, 0.737, value, 18, TEAL, "bold")
        add_text(fig, x + 0.015, 0.711, label, 8.3, INK, "bold")
        add_text(fig, x + 0.015, 0.694, note, 6.8, MUTED)

    add_text(fig, 0.07, 0.646, "What is already usable", 11, INK, "bold")
    add_text(fig, 0.07, 0.619,
             "• Live XAU/USD analysis from BiQuote on H4, H1 and M15.\n"
             "• BUY/SELL LIMIT, BUY/SELL STOP and MARKET/IMMEDIATE scenarios.\n"
             "• Entry, SL, TP1/TP2, risk/reward, conditions and confluence grade.\n"
             "• Local logging and candle archive; optional Telegram and dashboard.\n"
             "• OANDA history replay and broker-CSV import for research.",
             8.2, INK, linespacing=1.5, va="top")

    add_text(fig, 0.07, 0.512, "What a signal does not mean", 11, INK, "bold")
    add_text(fig, 0.07, 0.485,
             "The scanner does not place or manage trades. A grade is a strategy\n"
             "confluence score, not a calibrated probability of winning. In data-only\n"
             "mode there is no connected account balance; risk checks use a $10,000\n"
             "fallback baseline. Do not treat that baseline as your account risk.",
             8.2, MUTED, linespacing=1.45, va="top")

    add_text(fig, 0.07, 0.405, "Replay snapshot  |  OANDA practice  |  23–29 Sep 2026",
             10.5, INK, "bold")
    add_text(fig, 0.07, 0.383,
             "317 signals across 418 M15 decisions; counts include unfilled and unresolved setups.",
             7.8, MUTED)

    labels = ["TP1", "Stop loss", "Unfilled", "Unresolved"]
    counts = [66, 55, 127, 69]
    colors = [GREEN, RED, BLUE, AMBER]
    pie_ax = fig.add_axes([0.075, 0.11, 0.39, 0.225])
    pie_ax.pie(
        counts, colors=colors, startangle=90, counterclock=False,
        autopct="%1.1f%%", pctdistance=0.68,
        textprops={"fontsize": 7.2, "color": WHITE, "weight": "bold"},
        wedgeprops={"linewidth": 1.2, "edgecolor": PAPER},
    )
    pie_ax.set_title("Share of all generated signals", fontsize=9,
                     color=INK, pad=4, weight="bold")
    bar_ax = fig.add_axes([0.555, 0.12, 0.36, 0.215])
    positions = list(range(len(labels)))
    bars = bar_ax.barh(positions, counts, color=colors, height=0.58)
    bar_ax.set_yticks(positions, labels=labels, fontsize=7.5, color=INK)
    bar_ax.invert_yaxis()
    bar_ax.set_xlim(0, 150)
    bar_ax.set_xticks([0, 50, 100, 150])
    bar_ax.set_axisbelow(True)
    bar_ax.grid(axis="x", color=GRID, linewidth=0.7)
    bar_ax.set_title("Outcome counts (n = 317)", fontsize=9,
                     color=INK, pad=4, weight="bold")
    for spine in bar_ax.spines.values():
        spine.set_visible(False)
    bar_ax.tick_params(axis="both", length=0)
    bar_ax.tick_params(axis="x", labelsize=7, labelcolor=MUTED)
    for bar, count in zip(bars, counts):
        percent = count / sum(counts) * 100
        bar_ax.text(count + 3, bar.get_y() + bar.get_height() / 2,
                    f"{count}  |  {percent:.1f}%", va="center",
                    fontsize=7.1, color=INK)

    add_text(fig, 0.07, 0.078,
             "Resolved-only hit rate = 66 / (66 + 55) = 54.5%. This is not a 54.5% probability for a new signal.",
             7.6, INK, "bold")
    add_text(fig, 0.07, 0.054,
             "One short sample; candle-based estimates omit spread, slippage, fees and overlapping-position constraints.",
             7.1, MUTED)
    add_text(fig, 0.93, 0.025, "01 / 02", 7, MUTED, ha="right")
    pdf.savefig(fig, facecolor=fig.get_facecolor())
    plt.close(fig)


def page_two(pdf):
    fig = new_page()
    add_text(fig, 0.07, 0.914, "Use it now. Validate it next.", 24, INK, "bold")
    add_text(fig, 0.07, 0.884,
             "The project has a working signal pipeline; the next milestone is trustworthy evidence.",
             9.5, MUTED)

    add_text(fig, 0.07, 0.835, "What you can do with it today", 11, INK, "bold")
    actions = [
        ("1  Scan live", "python main.py",
         "Polls BiQuote; prints/logs candidate setups and archives fetched candles."),
        ("2  Open the dashboard", "streamlit run dashboard/app.py",
         "Review saved setups and signal types locally."),
        ("3  Replay archived history", "python -m scanner.signal_replay --source OANDA-PRACTICE --symbol XAU_USD",
         "Evaluate signals against later M15 candles; add --from / --to to bound dates."),
        ("4  Bring your broker data", "python -m scanner.import_market_csv <file> --symbol XAUUSD --timeframe H1 --source <broker>",
         "Keep broker candles separate; specify --timezone for timezone-naive exports."),
    ]
    row_y = [0.792, 0.718, 0.644, 0.570]
    for (title, command, detail), y in zip(actions, row_y):
        add_box(fig, 0.07, y - 0.055, 0.86, 0.065)
        add_text(fig, 0.085, y - 0.007, title, 8.5, INK, "bold")
        add_text(fig, 0.32, y - 0.007, command, 6.4, TEAL, "bold",
                 family="DejaVu Sans Mono")
        add_text(fig, 0.085, y - 0.034, detail, 7.4, MUTED)

    add_box(fig, 0.07, 0.427, 0.86, 0.098, color=INK, edge=INK)
    add_text(fig, 0.09, 0.493, "Confidence: early and uncalibrated", 11, WHITE, "bold")
    add_text(fig, 0.09, 0.466,
             "The replay shows a 54.5% hit rate among 121 resolved outcomes, not among all signals.\n"
             "127/317 were unfilled; 69/317 remained unresolved. Grades have not been mapped\n"
             "to probabilities, and one week cannot establish performance across market regimes.",
             8.0, WHITE, linespacing=1.35, va="top")

    add_text(fig, 0.07, 0.392, "Where we are heading", 11, INK, "bold")
    steps = [
        ("01  Match the feed", "Build a longer archive from the broker/feed\n"
         "you actually trade; XAU/USD prices differ."),
        ("02  Test realistic fills", "Replay multiple market regimes with spread,\n"
         "slippage, fees and position constraints."),
        ("03  Calibrate grades", "Report expectancy and outcomes by grade,\n"
         "signal type and held-out time periods."),
    ]
    for index, (title, detail) in enumerate(steps):
        x = 0.07 + index * 0.295
        add_box(fig, x, 0.267, 0.27, 0.099)
        add_text(fig, x + 0.013, 0.337, title, 8.1, TEAL, "bold")
        add_text(fig, x + 0.013, 0.312, detail, 7.3, INK,
                 linespacing=1.35, va="top")

    add_box(fig, 0.07, 0.105, 0.86, 0.126, color="#F1E8D7", edge="#E4D4B8")
    add_text(fig, 0.09, 0.204, "Critical operating caveats", 9.5, INK, "bold")
    add_text(fig, 0.09, 0.178,
             "• BiQuote is a rolling live feed; OANDA practice replay is a different price feed.\n"
             "• The scanner never executes trades. Verify levels and risk at your own broker.\n"
             "• Data-only risk checks use a $10,000 fallback balance, not your live equity.\n"
             "• Backtest outcomes are OHLC estimates, not a broker execution simulation.",
             7.7, INK, linespacing=1.42, va="top")

    add_text(fig, 0.07, 0.070,
             "Bottom line: usable for observing and researching candidate setups today; not yet proven as a profitable strategy.",
             8.1, INK, "bold")
    add_text(fig, 0.93, 0.025, "02 / 02", 7, MUTED, ha="right")
    pdf.savefig(fig, facecolor=fig.get_facecolor())
    plt.close(fig)


def main():
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with PdfPages(OUTPUT) as pdf:
        pdf.infodict()["Title"] = "SOLID XAU/USD SCAN AND ALERT RICHSCHEME 001 | Project Brief"
        pdf.infodict()["Subject"] = "Current capabilities, replay evidence, and next validation steps"
        pdf.infodict()["Author"] = "Trading Scanner Project"
        page_one(pdf)
        page_two(pdf)
    print(OUTPUT)


if __name__ == "__main__":
    main()