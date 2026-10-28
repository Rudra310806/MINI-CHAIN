contract ReviewReadyBank {
    state balance : int;
    state owner : address;
    state active : bool;
    state daily_limit : int;
    state transaction_count : int;
    state last_amount : int;

    function deposit(amount : int) {
        require(amount > 0);
        last_amount = amount;
        balance = balance + amount + 0;
        transaction_count = transaction_count + 1;
    }

    function withdraw(amount : int) {
        require(amount > 0);
        require(amount <= balance);
        last_amount = amount;
        balance = balance - amount;
        transaction_count = transaction_count + 1;
    }

    function changeOwner(new_owner : address) {
        require(active == true);
        owner = new_owner;
    }

    function setDailyLimit(new_limit : int) {
        require(new_limit > 0);
        daily_limit = new_limit;
    }

    function setActive(enabled : bool) {
        if (enabled == true) {
            active = true;
        } else {
            active = false;
        }
    }

    function getBalance() : int {
        return balance;
    }

    function getOwner() : address {
        return owner;
    }

    function estimateCharge(amount : int, rate : int) : int {
        int base_charge = amount * rate;
        int service_charge = daily_limit + 1;
        return (base_charge + service_charge) + transaction_count;
    }

    function countSteps(limit : int) : int {
        int steps = 0;
        while (steps < limit) {
            steps = steps + 1;
        }
        return steps;
    }

    function isWithinLimit(amount : int) : bool {
        return amount <= daily_limit;
    }

    function recordAmount(amount : int) {
        require(amount >= 0);
        last_amount = amount;
    }

    function resetTransactionCount(new_count : int) {
        require(new_count >= 0);
        transaction_count = new_count;
    }

    function applyServiceFee(fee : int) {
        require(fee >= 0);
        balance = balance - fee;
        last_amount = fee;
        transaction_count = transaction_count + 1;
    }

    function canWithdraw(amount : int) : bool {
        return active && amount <= balance;
    }

    function remainingLimit(amount : int) : int {
        int remaining = daily_limit - amount;
        return remaining;
    }

    function setOwnerIfActive(recipient : address, enabled : bool) {
        if (enabled) {
            owner = recipient;
        } else {
            owner = owner;
        }
    }
}
