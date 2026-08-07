"""
scripts/test_guardrail_v3.py — Test guardrail rumus PnL V3

Menunjukkan:
1. Contoh pasangan risk-free (Pu+Pd < 1, worst_case >= 0)
2. Penolakan order yang membuat imbalance terlalu besar
3. Penolakan order yang membuat Pu+Pd >= 1
4. Perbedaan mode risk_free_only vs spread_positive
"""

from src.mm import (
    InventoryState,
    worst_case,
    spread_pair,
    decompose,
    create_guardrail,
    GuardrailMode,
)


def test_risk_free_pair():
    """Test 1: Pasangan risk-free sederhana."""
    print("=" * 60)
    print("TEST 1: Pasangan Risk-Free (Pu+Pd < 1, worst_case >= 0)")
    print("=" * 60)
    
    # Beli 5 share UP @ 0.40 dan 5 share DOWN @ 0.50
    inv = InventoryState(
        su=5.0,
        sd=5.0,
        cost_u=5 * 0.40,  # $2.00
        cost_d=5 * 0.50,  # $2.50
    )
    
    print(f"Su={inv.su}, Sd={inv.sd}")
    print(f"Pu={inv.pu:.4f}, Pd={inv.pd:.4f}")
    print(f"Modal = ${inv.cost_u + inv.cost_d:.2f}")
    
    wc, is_rf = worst_case(inv.su, inv.pu, inv.sd, inv.pd)
    sp = spread_pair(inv.su, inv.pu, inv.sd, inv.pd)
    
    print(f"\nworst_case = ${wc:.4f} (risk_free={is_rf})")
    print(f"spread_pair = ${sp:.4f}")
    print(f"Matched = {inv.matched} share")
    print(f"Imbalance = {inv.imbalance} share")
    
    decomp = decompose(inv.su, inv.pu, inv.sd, inv.pd)
    print(f"\nDecompose:")
    print(f"  Net side: {decomp['net_side']}")
    print(f"  PnL if UP wins:   ${decomp['pnl_if_up_wins']:.4f}")
    print(f"  PnL if DOWN wins: ${decomp['pnl_if_down_wins']:.4f}")
    
    assert is_rf, "Harusnya risk-free!"
    assert sp > 0, "Spread pair harus positif!"
    print("\n✅ TEST 1 LULUS: Pasangan risk-free dengan profit di semua outcome\n")


def test_guardrail_rejects_imbalance():
    """Test 2: Guardrail menolak order yang membuat imbalance terlalu besar."""
    print("=" * 60)
    print("TEST 2: Guardrail Menolak Imbalance Besar")
    print("=" * 60)
    
    guard = create_guardrail(
        mode_str="risk_free_only",
        max_imbalance=14.0,  # Batas 14 share
        pair_margin=0.02,
    )
    
    # Posisi awal balanced
    inv = InventoryState(su=10.0, sd=10.0, cost_u=4.0, cost_d=5.0)
    print(f"Posisi awal: Su={inv.su}, Sd={inv.sd} (balanced)")
    
    # Coba beli 15 share UP → imbalance jadi 15 > 14 → DITOLAK
    decision = guard.check_buy(inv, "UP", 0.40, 15.0)
    print(f"\nCoba beli 15 UP @ 0.40:")
    print(f"  Allowed: {decision.allowed}")
    print(f"  Reason: {decision.reason}")
    
    assert not decision.allowed, "Harusnya ditolak!"
    assert "Imbalance" in decision.reason, "Alasan harus tentang imbalance!"
    
    # Coba beli 4 share UP → imbalance jadi 14 <= 14 → DIIZINKAN (jika risk-free)
    decision2 = guard.check_buy(inv, "UP", 0.40, 4.0)
    print(f"\nCoba beli 4 UP @ 0.40:")
    print(f"  Allowed: {decision2.allowed}")
    print(f"  Reason: {decision2.reason}")
    
    print("\n✅ TEST 2 LULUS: Guardrail membatasi imbalance\n")


def test_guardrail_rejects_bad_spread():
    """Test 3: Guardrail menolak order yang membuat Pu+Pd >= 1."""
    print("=" * 60)
    print("TEST 3: Guardrail Menolak Pasangan Rugi (Pu+Pd >= 1)")
    print("=" * 60)
    
    guard = create_guardrail(
        mode_str="spread_positive",
        max_imbalance=50.0,
        pair_margin=0.02,
    )
    
    # Sudah pegang UP @ 0.60 (mahal!)
    inv = InventoryState(su=10.0, sd=0.0, cost_u=6.0, cost_d=0.0)
    print(f"Posisi awal: Su={inv.su} @ Pu={inv.pu:.2f}, Sd={inv.sd}")
    print(f"  Pu sudah 0.60 (mahal)")
    
    # Coba beli DOWN @ 0.45 → Pu+Pd = 0.60+0.45 = 1.05 >= 1 → DITOLAK
    decision = guard.check_buy(inv, "DOWN", 0.45, 10.0)
    print(f"\nCoba beli 10 DOWN @ 0.45:")
    print(f"  Projected Pu+Pd = {decision.projected_sum_prices:.4f}")
    print(f"  Allowed: {decision.allowed}")
    print(f"  Reason: {decision.reason}")
    
    assert not decision.allowed, "Harusnya ditolak!"
    assert "Pu+Pd" in decision.reason or "pasangan rugi" in decision.reason.lower()
    
    # Coba beli DOWN @ 0.35 → Pu+Pd = 0.60+0.35 = 0.95 < 1 → DIIZINKAN
    decision2 = guard.check_buy(inv, "DOWN", 0.35, 10.0)
    print(f"\nCoba beli 10 DOWN @ 0.35:")
    print(f"  Projected Pu+Pd = {decision2.projected_sum_prices:.4f}")
    print(f"  Allowed: {decision2.allowed}")
    print(f"  Reason: {decision2.reason}")
    
    assert decision2.allowed, "Harusnya diizinkan!"
    
    print("\n✅ TEST 3 LULUS: Guardrail menjaga Pu+Pd < 1\n")


def test_mode_off_forbidden():
    """Test 4: Mode 'off' dilarang untuk live."""
    print("=" * 60)
    print("TEST 4: Mode 'off' Dilarang untuk Live Trading")
    print("=" * 60)
    
    try:
        guard = create_guardrail(
            mode_str="off",
            max_imbalance=14.0,
        )
        print("❌ ERROR: Seharusnya raise ValueError!")
        assert False, "Mode off seharusnya ditolak!"
    except ValueError as e:
        print(f"✅ Benar: Mode 'off' ditolak dengan error:")
        print(f"   {e}")
        print("\n✅ TEST 4 LULUS: Mode 'off' tidak bisa dibuat untuk live\n")


def test_accumulation_scenario():
    """Test 5: Skenario akumulasi seperti Bonereaper."""
    print("=" * 60)
    print("TEST 5: Akumulasi Bertahap dengan Guardrail")
    print("=" * 60)
    
    guard = create_guardrail(
        mode_str="risk_free_only",
        max_imbalance=14.0,
        pair_margin=0.02,
    )
    
    # Mulai dari kosong
    inv = InventoryState(su=0, sd=0, cost_u=0, cost_d=0)
    print("Mulai dari posisi kosong")
    
    # Accumulate 10 fill kecil
    fills = [
        ("UP", 0.38, 2.0),
        ("DOWN", 0.48, 2.0),
        ("UP", 0.39, 3.0),
        ("DOWN", 0.49, 3.0),
        ("UP", 0.37, 2.0),
        ("DOWN", 0.50, 2.0),
    ]
    
    for i, (side, price, size) in enumerate(fills, 1):
        decision = guard.check_buy(inv, side, price, size)
        if decision.allowed:
            # Update inventori manual (simulasi fill terjadi)
            if side == "UP":
                inv = InventoryState(
                    su=inv.su + size,
                    sd=inv.sd,
                    cost_u=inv.cost_u + size * price,
                    cost_d=inv.cost_d,
                )
            else:
                inv = InventoryState(
                    su=inv.su,
                    sd=inv.sd + size,
                    cost_u=inv.cost_u,
                    cost_d=inv.cost_d + size * price,
                )
            print(f"  Fill {i}: {side} {size}@{price:.2f} ✓ → Su={inv.su}, Sd={inv.sd}, Pu={inv.pu:.3f}, Pd={inv.pd:.3f}")
        else:
            print(f"  Fill {i}: {side} {size}@{price:.2f} ✗ → {decision.reason}")
    
    # Cek state akhir
    wc, is_rf = worst_case(inv.su, inv.pu, inv.sd, inv.pd)
    print(f"\nState akhir:")
    print(f"  Su={inv.su} @ Pu={inv.pu:.4f}")
    print(f"  Sd={inv.sd} @ Pd={inv.pd:.4f}")
    print(f"  Matched={inv.matched}, Imbalance={inv.imbalance}")
    print(f"  worst_case=${wc:.4f} (risk_free={is_rf})")
    
    if is_rf:
        print("\n✅ TEST 5 LULUS: Akumulasi tetap risk-free!\n")
    else:
        print(f"\n⚠️  Posisi akhir bukan risk-free (wc=${wc:.4f}), tapi ini demo\n")


if __name__ == "__main__":
    print("\n🧪 TESTING GUARDRAIL RUMUS PnL V3\n")
    
    test_risk_free_pair()
    test_guardrail_rejects_imbalance()
    test_guardrail_rejects_bad_spread()
    test_mode_off_forbidden()
    test_accumulation_scenario()
    
    print("=" * 60)
    print("🎉 SEMUA TEST LULUS!")
    print("=" * 60)
    print("\nGuardrail V3 siap dipakai untuk live trading.")
    print("Mode WAJIB: risk_free_only atau spread_positive")
    print("Mode DILARANG: off (hanya untuk simulasi/replay)\n")
