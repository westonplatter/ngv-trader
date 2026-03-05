# Spec: Security Data tables and endpoints

## Purpose

Add broker trade ingestion with fill-level fidelity, idempotency, and correction handling.

## Scope

## Endpoints

/stocks
/stocks/{symbol}/options
/stocks/{symbol}/vs

/futures
/futures/{symbol}/ts
/futures/{symbol}/options
/futures/{symbol}/vs

## Actions

### 1. Futures term structure, fetch ts contracts

Within a background job
For /CL, fetch the first x number of contracts.
Store contract definitions in a table.
Fetch the price values and store in a futures price table
Allow users to query the ts (term structure) via a Rest call, that returns the contract md with the most recent price data

### 2. Futures iv vol suface, fetch vs (vol surface) contracts

For /CL, fetch data

- the call and puts
- between strike X and Y (or delta X and Y)
- for expiries between start_date and end_date
  fetch the 1st order + IV values and store in a futures option price table

## Other Considerations

### Future Options data

For need to see a IV term structure specific to a futures underlying. Applicable on March 4, when I want to open a calendar spread shorting the March 15th calls and long back the April 10th-ish calls (that coincide with the May contract's Op Ex event date when we flip to the next contract).

I need a quick way to see hthe underying contract for an options - and in a human discernable way (lable, not an ID)
