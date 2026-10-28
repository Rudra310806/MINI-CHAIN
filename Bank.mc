contract Bank {
    state balance : int;
    state amount : int;
    state fee : int;
    state total : int;
    state doubled : int;
    state quadrupled : int;
    state octupled : int;
    state largeMultiple : int;
    state constant : int;
    state shifted : int;

    function deposit(amount : int) {
        balance = balance + amount;
        balance = balance + 1;
        doubled = amount * 2;
        quadrupled = amount * 4;
        octupled = amount * 8;
        largeMultiple = amount * 16;
        fee = 2 * 4;
        total = 10 + 20;
        constant = 3 * 8 + 5;
        shifted = 64 >> 2;
    }

    function withdraw(amount : int) {
        balance = balance - amount;
        require(amount > 0);
    }

    function transfer(amount : int) {
        balance = balance - amount;
    }
}