contract Bank {
    state balance : int;

    function deposit(amount : int) : int {
        int adjusted = amount;
        int doubled = (amount * 2);
        int fee = (3 * 4);
        require((amount > 0));
        balance = (balance + amount);
        return (doubled + fee);
    }

    function withdraw(amount : int) {
        require((amount > 0));
        require((amount <= balance));
        balance = (balance - amount);
    }
}
