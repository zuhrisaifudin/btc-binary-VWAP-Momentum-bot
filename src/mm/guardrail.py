"""
src/mm/guardrail.py — Guardrail rumus PnL (keputusan order)

Mode:
- risk_free_only  → PLACE hanya jika worst_case >= 0
- spread_positive → PLACE hanya jika Pu+Pd < 1 - pair_margin
- off             → PLACE selalu (TIDAK BOLEH untuk live!)

Guardrail ini DIPANGGIL sebelum setiap order place.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Tuple, Optional

from .pnl_formula import (
    InventoryState,
    worst_case,
    sum_prices,
    project_fill,
)


class GuardrailMode(str, Enum):
    RISK_FREE_ONLY = "risk_free_only"
    SPREAD_POSITIVE = "spread_positive"
    OFF = "off"


@dataclass(frozen=True)
class GuardrailConfig:
    """Konfigurasi guardrail."""
    mode: GuardrailMode
    max_imbalance_shares: float  # batas imbalance absolut
    pair_margin: float = 0.02    # margin aman untuk Pu+Pd < 1
    
    def validate(self):
        """Validasi config saat startup."""
        if self.mode == GuardrailMode.OFF:
            raise ValueError(
                "GUARDRAIL MODE 'off' DILARANG UNTUK LIVE TRADING! "
                "Gunakan 'risk_free_only' atau 'spread_positive'."
            )
        if self.max_imbalance_shares <= 0:
            raise ValueError("max_imbalance_shares harus > 0")
        if self.pair_margin < 0 or self.pair_margin > 0.5:
            raise ValueError("pair_margin harus antara 0 dan 0.5")


@dataclass(frozen=True)
class GuardrailDecision:
    """Hasil keputusan guardrail."""
    allowed: bool
    reason: str
    projected_wc: Optional[float] = None
    projected_sum_prices: Optional[float] = None
    projected_imbalance: Optional[float] = None


class Guardrail:
    """
    Guardrail inti Bot V3.
    
    Dipanggil SEBELUM setiap order place untuk memastikan:
    1. Imbalance tidak melebihi batas
    2. Mode risk_free_only: worst_case >= 0
    3. Mode spread_positive: Pu+Pd < 1 - pair_margin
    """
    
    def __init__(self, cfg: GuardrailConfig):
        self.cfg = cfg
    
    def check_buy(
        self,
        inv: InventoryState,
        side: str,
        price: float,
        size: float
    ) -> GuardrailDecision:
        """
        Cek apakah order BUY diizinkan.
        
        Args:
            inv: inventori sekarang
            side: 'UP' atau 'DOWN'
            price: harga bid
            size: jumlah share
        
        Returns:
            GuardrailDecision(allowed, reason, ...)
        """
        # Proyeksikan state PASCA-fill
        proj = project_fill(inv, side, price, size)
        
        # Hitung metrik proyeksi
        wc, is_rf = worst_case(proj.su, proj.pu, proj.sd, proj.pd)
        sp = sum_prices(proj.pu, proj.pd)
        imb = proj.imbalance
        
        # 1. Cek imbalance (universal, semua mode)
        if imb > self.cfg.max_imbalance_shares:
            return GuardrailDecision(
                allowed=False,
                reason=f"Imbalance {imb:.2f} > max {self.cfg.max_imbalance_shares}",
                projected_wc=wc,
                projected_sum_prices=sp,
                projected_imbalance=imb,
            )
        
        # 2. Cek berdasarkan mode
        if self.cfg.mode == GuardrailMode.RISK_FREE_ONLY:
            if not is_rf:
                return GuardrailDecision(
                    allowed=False,
                    reason=f"Bukan risk-free (worst_case={wc:.4f} < 0)",
                    projected_wc=wc,
                    projected_sum_prices=sp,
                    projected_imbalance=imb,
                )
        
        elif self.cfg.mode == GuardrailMode.SPREAD_POSITIVE:
            threshold = 1 - self.cfg.pair_margin
            if sp >= threshold:
                return GuardrailDecision(
                    allowed=False,
                    reason=f"Pu+Pd={sp:.4f} >= {threshold:.4f} (pasangan rugi)",
                    projected_wc=wc,
                    projected_sum_prices=sp,
                    projected_imbalance=imb,
                )
        
        # elif self.cfg.mode == GuardrailMode.OFF:
        #     # Tidak ada cek, izinkan semua (HANYA untuk simulasi/replay!)
        #     pass
        
        # Lolos semua guardrail
        return GuardrailDecision(
            allowed=True,
            reason="OK",
            projected_wc=wc,
            projected_sum_prices=sp,
            projected_imbalance=imb,
        )
    
    def check_buys(
        self,
        inv: InventoryState,
        candidates: list[Tuple[str, float, float]]
    ) -> list[Tuple[str, float, float, GuardrailDecision]]:
        """
        Cek banyak kandidat order sekaligus.
        
        Args:
            candidates: [(side, price, size), ...]
        
        Returns:
            [(side, price, size, decision), ...]
        """
        results = []
        for side, price, size in candidates:
            decision = self.check_buy(inv, side, price, size)
            results.append((side, price, size, decision))
        return results


def create_guardrail(mode_str: str, max_imbalance: float, pair_margin: float = 0.02) -> Guardrail:
    """Factory function untuk membuat Guardrail dari string config."""
    mode = GuardrailMode(mode_str.lower())
    cfg = GuardrailConfig(
        mode=mode,
        max_imbalance_shares=max_imbalance,
        pair_margin=pair_margin,
    )
    cfg.validate()  # Akan raise jika mode=off
    return Guardrail(cfg)
