"""Debug script: inspect reqSecDefOptParams results for CL."""

from ib_async import IB, Index

ib = IB()
ib.connect("127.0.0.1", 7496, clientId=99)

underlying_symbol = "CL"
contract_exchange = "NYMEX"
contract_currency = "USD"

index = Index(underlying_symbol, contract_exchange, currency=contract_currency)
ib.qualifyContracts(index)
print(f"Index: {index}")
print(f"  conId={index.conId}, secType={index.secType}")
print()

chains = ib.reqSecDefOptParams(
    underlyingSymbol=index.symbol,
    futFopExchange=index.exchange,
    underlyingSecType=index.secType,
    underlyingConId=index.conId,
)

print(f"Chains returned: {len(chains)}")
for i, chain in enumerate(chains):
    print(f"\n--- Chain {i} ---")
    print(f"  type: {type(chain)}")
    print(f"  dir:  {[a for a in dir(chain) if not a.startswith('_')]}")
    print(f"  repr: {chain}")
    # Check specific attributes
    for attr in ("underlyingConId", "exchange", "tradingClass", "multiplier"):
        val = getattr(chain, attr, "MISSING")
        print(f"  {attr} = {val!r} (type={type(val).__name__})")
    expirations = getattr(chain, "expirations", set())
    strikes = getattr(chain, "strikes", set())
    print(f"  expirations: {len(expirations)} entries, first 5: {sorted(expirations)[:5]}")
    print(f"  strikes: {len(strikes)} entries, first 5: {sorted(strikes)[:5]}")

ib.disconnect()
