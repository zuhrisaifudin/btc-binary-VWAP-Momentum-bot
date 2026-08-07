"""
scripts/demo_quote_engine_v3.py — Demo Quote Engine V3

Menunjukkan:
1. Profil waktu: taker saat buka, maker-dominan di tengah, maker-only di akhir
2. Cap dinamis harga dari rumus Pu+Pd < 1
3. Sizing berdasarkan saldo tersedia
4. Fase eksekusi berubah otomatis
"""

from src.mm.quotes import (
    OrderBook, BookLevel,
    QuoteConfig, QuoteEngine,
    ExecutionPhase,
)


def demo_phase_transitions():
    """Demo 1: Transisi fase dari buka hingga settle."""
    print("=" * 70)
    print("DEMO 1: Transisi Fase Eksekusi (Buka → Settle)")
    print("=" * 70)
    
    cfg = QuoteConfig(
        taker_until_s=295.0,
        maker_only_below_s=60.0,
        taper_size_below_s=15.0,
    )
    engine = QuoteEngine(cfg)
    
    # Simulasi waktu dari 300s hingga 0s
    test_times = [300, 295, 240, 180, 120, 60, 30, 15, 5, 0]
    
    print(f"{'Waktu (s)':<12} | {'Fase':<15} | {'Taker?':<8}")
    print("-" * 70)
    
    for t in test_times:
        phase = engine.get_phase(t)
        is_taker = engine.should_be_taker(phase, t)
        print(f"{t:<12} | {phase.value:<15} | {'Ya' if is_taker else 'Tidak':<8}")
    
    print("\n📈 Pola:")
    print("   - t > 295s: TAKER agresif (rebut posisi awal)")
    print("   - 60-295s: MAKER-dominan (grid dua sisi)")
    print("   - t < 60s: MAKER-only (tidak seberang spread)")
    print("   - t < 15s: Size mengecil (taper)")
    print()


def demo_price_cap_from_formula():
    """Demo 2: Cap harga dinamis dari rumus Pu+Pd < 1."""
    print("=" * 70)
    print("DEMO 2: Cap Harga Dinamis (Pu+Pd < 1)")
    print("=" * 70)
    
    cfg = QuoteConfig(pair_margin=0.02)
    engine = QuoteEngine(cfg)
    
    # Skenario 1: Sudah pegang UP murah @ 0.40
    print("\nSkenario A: Sudah pegang UP @ Pu=0.40 (murah)")
    print("  → Cap harga DOWN = 1 - 0.40 - 0.02 = 0.58")
    cap_down = engine.calculate_price_cap("DOWN", inv_pu=0.40, inv_pd=0.0)
    print(f"  → Cap aktual: {cap_down:.4f}")
    print(f"  → Boleh beli DOWN @ 0.55? {0.55 <= cap_down}")
    print(f"  → Boleh beli DOWN @ 0.60? {0.60 <= cap_down} (terlalu mahal!)")
    
    # Skenario 2: Sudah pegang UP mahal @ 0.60
    print("\nSkenario B: Sudah pegang UP @ Pu=0.60 (mahal)")
    print("  → Cap harga DOWN = 1 - 0.60 - 0.02 = 0.38")
    cap_down2 = engine.calculate_price_cap("DOWN", inv_pu=0.60, inv_pd=0.0)
    print(f"  → Cap aktual: {cap_down2:.4f}")
    print(f"  → Boleh beli DOWN @ 0.35? {0.35 <= cap_down2}")
    print(f"  → Boleh beli DOWN @ 0.45? {0.45 <= cap_down2} (terlalu mahal!)")
    print("  ⚠️  Jika beli @ 0.45 → Pu+Pd = 1.05 > 1 → PASANGAN RUGI!")
    
    # Skenario 3: Balanced position
    print("\nSkenario C: Balanced Pu=0.45, Pd=0.48")
    cap_up = engine.calculate_price_cap("UP", inv_pu=0.45, inv_pd=0.48)
    cap_down = engine.calculate_price_cap("DOWN", inv_pu=0.45, inv_pd=0.48)
    print(f"  → Cap UP: {cap_up:.4f} (harus ≤ 1 - 0.48 - 0.02)")
    print(f"  → Cap DOWN: {cap_down:.4f} (harus ≤ 1 - 0.45 - 0.02)")
    print(f"  → Kedua cap ketat karena sudah ada pasangan!")
    print()


def demo_quote_generation():
    """Demo 3: Generate quote dengan book simulasi."""
    print("=" * 70)
    print("DEMO 3: Generate Quote dengan Book In-Memory")
    print("=" * 70)
    
    cfg = QuoteConfig(
        taker_until_s=295.0,
        maker_only_below_s=60.0,
        min_shares=1.0,
        max_order_usd=2.50,
    )
    engine = QuoteEngine(cfg)
    
    # Buat book simulasi
    book = OrderBook(
        condition_id="btc-5min-aug7",
        bids_up=[BookLevel(0.42, 100), BookLevel(0.41, 200)],
        asks_up=[BookLevel(0.45, 100), BookLevel(0.46, 200)],
        bids_down=[BookLevel(0.48, 100), BookLevel(0.47, 200)],
        asks_down=[BookLevel(0.52, 100), BookLevel(0.53, 200)],
    )
    
    print("\nOrder Book:")
    print(f"  UP:   bid={book.best_bid('UP'):.2f}, ask={book.best_ask('UP'):.2f}")
    print(f"  DOWN: bid={book.best_bid('DOWN'):.2f}, ask={book.best_ask('DOWN'):.2f}")
    
    # Posisi awal kosong
    inv_su, inv_sd = 0.0, 0.0
    inv_cost_u, inv_cost_d = 0.0, 0.0
    balance = 20.0  # Modal simulasi $20
    
    print(f"\nSaldo tersedia: ${balance:.2f}")
    print("\n" + "-" * 70)
    
    # Simulasi 3 waktu berbeda
    test_scenarios = [
        (300, "Buka (taker)"),
        (180, "Tengah (maker)"),
        (30, "Akhir (maker-only)"),
    ]
    
    for secs_to_expiry, label in test_scenarios:
        print(f"\n⏱️  Waktu: {secs_to_expiry}s ({label})")
        
        # Buat QuoteRequest
        from src.mm.quotes import QuoteRequest
        from src.mm.pnl_formula import InventoryState
        
        inventory = InventoryState(
            su=inv_su,
            sd=inv_sd,
            cost_u=inv_cost_u,
            cost_d=inv_cost_d
        )
        
        request = QuoteRequest(
            market="BTC-2024Q4-100K",
            book=book,
            inventory=inventory,
            time_in_cycle=secs_to_expiry,
            available_balance=balance,
            open_orders_notional=0.0
        )
        
        quotes = engine.generate_quotes_two_sided_from_request(request)
        
        quote_up, quote_down = quotes
        
        if quote_up:
            print(f"  UP:   {quote_up.size}@${quote_up.price:.4f} "
                  f"[{quote_up.phase.value}, {'taker' if quote_up.is_taker else 'maker'}]")
        else:
            print(f"  UP:   SKIP")
        
        if quote_down:
            print(f"  DOWN: {quote_down.size}@${quote_down.price:.4f} "
                  f"[{quote_down.phase.value}, {'taker' if quote_down.is_taker else 'maker'}]")
        else:
            print(f"  DOWN: SKIP")
    
    print()


def demo_balance_sizing():
    """Demo 4: Sizing berdasarkan saldo."""
    print("=" * 70)
    print("DEMO 4: Sizing Berdasarkan Saldo Tersedia")
    print("=" * 70)
    
    cfg = QuoteConfig(max_order_usd=2.50, min_shares=1.0)
    engine = QuoteEngine(cfg)
    
    book = OrderBook(
        condition_id="test",
        bids_up=[BookLevel(0.40, 100)],
        asks_up=[BookLevel(0.45, 100)],
        bids_down=[BookLevel(0.45, 100)],
        asks_down=[BookLevel(0.50, 100)],
    )
    
    test_balances = [20.0, 10.0, 5.0, 2.0, 0.5]
    
    print(f"{'Saldo':<10} | {'Max Order USD':<15} | {'Size UP@0.40':<15}")
    print("-" * 70)
    
    for balance in test_balances:
        size = engine.calculate_size_from_balance(
            price=0.40,
            available_balance=balance,
            total_open_orders_notional=0.0,
        )
        max_usd = min(size * 0.40, cfg.max_order_usd)
        print(f"${balance:<9.2f} | ${max_usd:<14.2f} | {size:<14.2f} shares")
    
    print("\n💡 Semakin kecil saldo, semakin kecil size order.")
    print("   Max order USD membatasi exposure per leg.\n")


if __name__ == "__main__":
    print("\n🧪 DEMO QUOTE ENGINE V3\n")
    
    demo_phase_transitions()
    demo_price_cap_from_formula()
    demo_quote_generation()
    demo_balance_sizing()
    
    print("=" * 70)
    print("🎉 DEMO SELESAI!")
    print("=" * 70)
    print("\nQuote Engine V3 menghasilkan harga & size berdasarkan:")
    print("  1. ✅ Fase waktu (taker/maker)")
    print("  2. ✅ Book in-memory")
    print("  3. ✅ Cap rumus Pu+Pd < 1")
    print("  4. ✅ Saldo tersedia")
    print("\nKombinasi ini memastikan bot:")
    print("  - Rebut posisi cepat saat buka (taker)")
    print("  - Grid pasif di tengah (maker)")
    print("  - Tidak seberang spread dekat expiry (aman)")
    print("  - Selalu jaga Pu+Pd < 1 (pasangan untung)")
    print("  - Size proporsional dengan saldo (no over-leverage)\n")
