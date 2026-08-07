"""
src/mm/pnl_formula.py — Matematika PnL murni (domain logic)

Rumus inti Bot V3:
1. modal(Su, Pu, Sd, Pd) = Su*Pu + Sd*Pd
2. pnl_settle(side, Su, Pu, Sd, Pd):
   - UP menang:   PnL = Su - modal
   - DOWN menang: PnL = Sd - modal
3. worst_case(Su, Pu, Sd, Pd) = min(Su, Sd) - modal  → risk-free jika >= 0
4. spread_pair = M * (1 - Pu - Pd) dengan M = min(Su, Sd)
5. imbalance = |Su - Sd|
"""

from dataclasses import dataclass
from typing import Tuple


@dataclass(frozen=True)
class InventoryState:
    """Snapshot inventori untuk satu market."""
    su: float  # share Up
    sd: float  # share Down
    cost_u: float  # total biaya Up
    cost_d: float  # total biaya Down

    @property
    def pu(self) -> float:
        """Harga rata-rata Up (0 jika belum ada posisi)."""
        return self.cost_u / self.su if self.su > 0 else 0.0

    @property
    def pd(self) -> float:
        """Harga rata-rata Down (0 jika belum ada posisi)."""
        return self.cost_d / self.sd if self.sd > 0 else 0.0

    @property
    def matched(self) -> float:
        """Share berpasangan (M = min(Su, Sd))."""
        return min(self.su, self.sd)

    @property
    def imbalance(self) -> float:
        """Sisa arah telanjang (D = |Su - Sd|)."""
        return abs(self.su - self.sd)

    def net_side(self) -> str:
        """'UP', 'DOWN', atau 'BALANCED'."""
        if self.su > self.sd:
            return "UP"
        elif self.sd > self.su:
            return "DOWN"
        return "BALANCED"


def modal(su: float, pu: float, sd: float, pd: float) -> float:
    """[Rumus 1] Total modal terkunci."""
    return su * pu + sd * pd


def pnl_settle(side_wins: str, su: float, pu: float, sd: float, pd: float) -> float:
    """
    [Rumus 2] PnL saat settle berdasarkan outcome.
    
    Args:
        side_wins: 'UP' atau 'DOWN'
    
    Returns:
        PnL bruto (belum fee/rebate)
    """
    m = modal(su, pu, sd, pd)
    if side_wins == "UP":
        return su - m
    elif side_wins == "DOWN":
        return sd - m
    else:
        raise ValueError("side_wins harus 'UP' atau 'DOWN'")


def worst_case(su: float, pu: float, sd: float, pd: float) -> Tuple[float, bool]:
    """
    [Rumus 4] Worst-case PnL (skenario terburuk).
    
    Returns:
        (worst_pnl, is_risk_free)
        - worst_pnl < 0  → bisa rugi
        - worst_pnl >= 0 → risk-free (untung di semua outcome)
    """
    m = modal(su, pu, sd, pd)
    wc = min(su, sd) - m
    return wc, wc >= 0


def spread_pair(su: float, pu: float, sd: float, pd: float) -> float:
    """
    [Rumus 5a] Laba dari share berpasangan.
    
    spread_pair = M * (1 - Pu - Pd)
    Hanya positif jika Pu + Pd < 1 DAN M > 0
    """
    matched = min(su, sd)
    return matched * (1 - pu - pd)


def sum_prices(pu: float, pd: float) -> float:
    """[Rumus 5b] Pu + Pd — harus < 1 untuk pasangan untung."""
    return pu + pd


def decompose(su: float, pu: float, sd: float, pd: float) -> dict:
    """
    Decompose PnL menjadi komponen:
    - spread_pair: laba dari pasangan (M * (1 - Pu - Pd))
    - exposure_up: risiko sisi Up telanjang
    - exposure_down: risiko sisi Down telanjang
    """
    matched = min(su, sd)
    imbalance = abs(su - sd)
    spread = matched * (1 - pu - pd)
    
    if su > sd:
        # Net Up
        exposure = imbalance * (1 - pu)  # profit jika UP menang
        exposure_loss = -imbalance * pu  # loss jika DOWN menang
        return {
            "spread_pair": spread,
            "matched": matched,
            "imbalance": imbalance,
            "net_side": "UP",
            "pnl_if_up_wins": spread + exposure,
            "pnl_if_down_wins": spread + exposure_loss,
        }
    elif sd > su:
        # Net Down
        exposure = imbalance * (1 - pd)  # profit jika DOWN menang
        exposure_loss = -imbalance * pd  # loss jika UP menang
        return {
            "spread_pair": spread,
            "matched": matched,
            "imbalance": imbalance,
            "net_side": "DOWN",
            "pnl_if_up_wins": spread + exposure_loss,
            "pnl_if_down_wins": spread + exposure,
        }
    else:
        # Balanced
        return {
            "spread_pair": spread,
            "matched": matched,
            "imbalance": 0,
            "net_side": "BALANCED",
            "pnl_if_up_wins": spread,
            "pnl_if_down_wins": spread,
        }


def project_fill(
    inv: InventoryState,
    side: str,
    price: float,
    size: float
) -> InventoryState:
    """
    Proyeksikan state inventori PASCA-fill (untuk guardrail check).
    
    Args:
        inv: state sekarang
        side: 'UP' atau 'DOWN'
        price: harga fill
        size: jumlah share
    
    Returns:
        InventoryState baru (immutable)
    """
    if side == "UP":
        new_su = inv.su + size
        new_cost_u = inv.cost_u + size * price
        return InventoryState(
            su=new_su,
            sd=inv.sd,
            cost_u=new_cost_u,
            cost_d=inv.cost_d
        )
    elif side == "DOWN":
        new_sd = inv.sd + size
        new_cost_d = inv.cost_d + size * price
        return InventoryState(
            su=inv.su,
            sd=new_sd,
            cost_u=inv.cost_u,
            cost_d=new_cost_d
        )
    else:
        raise ValueError("side harus 'UP' atau 'DOWN'")
