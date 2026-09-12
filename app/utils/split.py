"""
Bill-splitting logic.
Each function takes total_amount + a list of member user_ids (+ extra data
for custom/percentage modes) and returns {user_id: amount} rounded to 2dp,
with any rounding remainder adjusted onto the last member so the shares
always sum exactly to total_amount.
"""


def _fix_rounding(shares: dict, total_amount: float) -> dict:
    rounded = {uid: round(amt, 2) for uid, amt in shares.items()}
    diff = round(total_amount - sum(rounded.values()), 2)
    if diff and rounded:
        last_key = list(rounded.keys())[-1]
        rounded[last_key] = round(rounded[last_key] + diff, 2)
    return rounded


def split_equal(total_amount: float, member_ids: list) -> dict:
    if not member_ids:
        return {}
    share = total_amount / len(member_ids)
    return _fix_rounding({uid: share for uid in member_ids}, total_amount)


def split_custom(total_amount: float, custom_amounts: dict) -> dict:
    """
    custom_amounts: {user_id: amount}
    Raises ValueError if amounts don't sum (within 1 paisa) to total_amount.
    """
    total_given = round(sum(custom_amounts.values()), 2)
    if abs(total_given - round(total_amount, 2)) > 0.01:
        raise ValueError(
            f"Custom amounts sum to {total_given}, but bill total is {total_amount}."
        )
    return {uid: round(amt, 2) for uid, amt in custom_amounts.items()}


def split_percentage(total_amount: float, percentages: dict) -> dict:
    """
    percentages: {user_id: percent} - must sum to 100 (within 0.01 tolerance)
    """
    total_pct = round(sum(percentages.values()), 2)
    if abs(total_pct - 100.0) > 0.01:
        raise ValueError(f"Percentages sum to {total_pct}%, must total 100%.")
    shares = {uid: total_amount * (pct / 100.0) for uid, pct in percentages.items()}
    return _fix_rounding(shares, total_amount)


def compute_balances(shares_by_bill: list) -> dict:
    """
    Given a list of dicts: {"paid_by": user_id, "shares": {user_id: amount}}
    across many bills, compute net balance per user:
        positive => this user is owed money overall
        negative => this user owes money overall
    """
    net = {}
    for bill in shares_by_bill:
        payer = bill["paid_by"]
        for uid, amt in bill["shares"].items():
            if uid == payer:
                continue
            net[uid] = net.get(uid, 0) - amt      # this member owes `amt`
            net[payer] = net.get(payer, 0) + amt   # payer is owed `amt`
    return {uid: round(v, 2) for uid, v in net.items()}


def simplify_debts(net_balances: dict) -> list:
    """
    Turns net balances into a minimal list of "who owes whom" transactions.
    Returns list of dicts: {"from": user_id, "to": user_id, "amount": float}
    """
    creditors = sorted(
        [(uid, amt) for uid, amt in net_balances.items() if amt > 0.01],
        key=lambda x: -x[1],
    )
    debtors = sorted(
        [(uid, -amt) for uid, amt in net_balances.items() if amt < -0.01],
        key=lambda x: -x[1],
    )
    transactions = []
    i, j = 0, 0
    creditors, debtors = list(creditors), list(debtors)
    while i < len(debtors) and j < len(creditors):
        debtor_id, debt_amt = debtors[i]
        creditor_id, credit_amt = creditors[j]
        pay_amt = round(min(debt_amt, credit_amt), 2)
        if pay_amt > 0:
            transactions.append({"from": debtor_id, "to": creditor_id, "amount": pay_amt})
        debtors[i] = (debtor_id, round(debt_amt - pay_amt, 2))
        creditors[j] = (creditor_id, round(credit_amt - pay_amt, 2))
        if debtors[i][1] <= 0.01:
            i += 1
        if creditors[j][1] <= 0.01:
            j += 1
    return transactions
