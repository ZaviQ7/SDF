import os
from typing import Dict, List, Any
from rich.console import Console
from rich.layout import Layout
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.align import Align

class TerminalDashboard:
    """Beautiful Rich terminal dashboard for tracking trading bot status in real-time."""
    
    def __init__(self):
        self.console = Console()
        
    def render(
        self,
        risk_summary: Dict[str, Any],
        edges: List[Dict[str, Any]],
        positions: List[Dict[str, Any]],
        resting_orders: List[Dict[str, Any]],
        logs: List[str],
        dry_run: bool
    ):
        """Render the complete trading dashboard layout to the terminal."""
        # Clear screen (works on Windows/Unix)
        os.system('cls' if os.name == 'nt' else 'clear')
        
        # Create root layout
        layout = Layout()
        
        # Split into header, body, footer
        layout.split(
            Layout(name="header", size=3),
            Layout(name="body", ratio=1),
            Layout(name="footer", size=8)
        )
        
        # Split body into left (portfolio) and right (edges & positions)
        layout["body"].split_row(
            Layout(name="portfolio", ratio=1),
            Layout(name="markets", ratio=2)
        )
        
        # Render Header
        mode_text = "[bold yellow]SIMULATION / DRY RUN[/]" if dry_run else "[bold green]LIVE TRADING[/]"
        header_text = Text.from_markup(f"🌤️  [bold white]STEAK DINNER FUND (SDF) - KALSHI WEATHER BOT[/]  |  Mode: {mode_text}")
        layout["header"].update(Panel(Align.center(header_text), border_style="blue"))
        
        # Render Portfolio Info (Left side)
        port_table = Table(show_header=False, box=None)
        port_table.add_column("Metric", style="cyan", width=18)
        port_table.add_column("Value", style="bold white")
        
        # Format metrics
        balance = risk_summary.get("bankroll", 30.00)
        exposure = risk_summary.get("total_exposure", 0.0)
        daily_pnl = risk_summary.get("daily_pnl", 0.0)
        pnl_style = "green" if daily_pnl >= 0 else "red"
        
        port_table.add_row("Total Bankroll:", f"${balance:.2f}")
        port_table.add_row("Open Exposure:", f"${exposure:.2f} ({risk_summary.get('exposure_pct', 0.0):.1f}%)")
        port_table.add_row("Cash Reserves:", f"${balance - exposure:.2f} ({100.0 - risk_summary.get('exposure_pct', 0.0):.1f}%)")
        port_table.add_row("Daily P&L:", f"[{pnl_style}]${daily_pnl:+.2f}[/]")
        port_table.add_row("Open Positions:", str(risk_summary.get("open_positions", 0)))
        port_table.add_row("Max Positions:", str(risk_summary.get("max_positions", 5)))
        port_table.add_row("Daily Loss Limit:", f"${risk_summary.get('daily_loss_limit', 6.00):.2f}")
        
        layout["portfolio"].update(Panel(port_table, title="[bold cyan]Account Summary[/]", border_style="cyan"))
        
        # Render Markets (Edges, Positions, Resting orders - Right side)
        markets_layout = Layout()
        markets_layout.split(
            Layout(name="edges_layout", ratio=1),
            Layout(name="positions_layout", ratio=1)
        )
        
        # 1. Edges Table
        edges_table = Table(title="[bold green]Detected Edges (EV >= 5%)[/]", title_align="left", expand=True)
        edges_table.add_column("Ticker", style="dim", width=25)
        edges_table.add_column("Play", style="bold")
        edges_table.add_column("Entry", justify="right")
        edges_table.add_column("Model Prob", justify="right")
        edges_table.add_column("Net EV", justify="right", style="green")
        
        for e in edges[:5]:
            play_style = "bold green" if e["side"] == "yes" else "bold red"
            edges_table.add_row(
                e["ticker"],
                f"[{play_style}]{e['side'].upper()}[/]",
                f"{int(e['entry_price']*100)}¢",
                f"{e['model_prob']:.1%}",
                f"{e['net_ev']*100:+.1%}"
            )
            
        if not edges:
            edges_table.add_row("No edges meeting threshold found.", "", "", "", "")
            
        markets_layout["edges_layout"].update(edges_table)
        
        # 2. Positions Table
        pos_table = Table(title="[bold magenta]Active Positions[/]", title_align="left", expand=True)
        pos_table.add_column("Ticker", style="dim", width=25)
        pos_table.add_column("Side")
        pos_table.add_column("Contracts", justify="right")
        pos_table.add_column("Avg Price", justify="right")
        pos_table.add_column("Current Price", justify="right")
        pos_table.add_column("PnL", justify="right")
        
        for p in positions:
            side_style = "bold green" if p["side"] == "yes" else "bold red"
            pnl_val = p.get("pnl", 0.0)
            pnl_disp_style = "green" if pnl_val >= 0 else "red"
            pos_table.add_row(
                p["ticker"],
                f"[{side_style}]{p['side'].upper()}[/]",
                str(p["size"]),
                f"{int(p['avg_price']*100)}¢",
                f"{int(p['current_value']*100)}¢",
                f"[{pnl_disp_style}]${pnl_val:+.2f}[/]"
            )
            
        if not positions:
            pos_table.add_row("No active positions.", "", "", "", "", "")
            
        markets_layout["positions_layout"].update(pos_table)
        
        layout["body"]["markets"].update(markets_layout)
        
        # Render Footer (Resting Orders & Logs)
        footer_layout = Layout()
        footer_layout.split_row(
            Layout(name="resting_orders", ratio=1),
            Layout(name="logs_layout", ratio=1)
        )
        
        # Resting Orders Table
        resting_table = Table(title="[bold yellow]Resting Orders[/]", title_align="left", expand=True)
        resting_table.add_column("ID", style="dim", width=15)
        resting_table.add_column("Ticker", style="dim")
        resting_table.add_column("Side")
        resting_table.add_column("Contracts", justify="right")
        resting_table.add_column("Price", justify="right")
        
        for o in resting_orders:
            side_style = "bold green" if o["side"] == "yes" else "bold red"
            resting_table.add_row(
                o["order_id"],
                o["ticker"],
                f"[{side_style}]{o['side'].upper()}[/]",
                str(o["size"]),
                f"{int(o['price']*100)}¢"
            )
            
        if not resting_orders:
            resting_table.add_row("No resting orders.", "", "", "", "")
            
        footer_layout["resting_orders"].update(resting_table)
        
        # Logs Feed
        log_text = Text()
        for log in logs[-5:]:
            log_text.append(log + "\n")
            
        footer_layout["logs_layout"].update(Panel(log_text, title="[bold white]Activity Feed[/]", border_style="white"))
        
        layout["footer"].update(footer_layout)
        
        # Draw everything
        self.console.print(layout)
