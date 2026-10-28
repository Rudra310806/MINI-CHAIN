contract SupplyChain {
    state status : string;
    state owner : address;
    state quantity : int;
    state fee : int;
    state total : int;
    state doubled : int;
    state quadrupled : int;
    state octupled : int;
    state largeMultiple : int;
    state constant : int;
    state shifted : int;

    function registerProduct(quantity : int) {
        doubled = quantity * 2;
        quadrupled = quantity * 4;
        octupled = quantity * 8;
        largeMultiple = quantity * 16;
        fee = 2 * 4;
        total = 10 + 20;
        constant = 3 * 8 + 5;
        shifted = 64 >> 2;
    }

    function dispatchProduct() {
        status = "dispatched";
        quantity = quantity + 1;
    }

    function deliverProduct() {
        status = "delivered";
    }

    function transferOwnership(newOwner : address) {
        owner = newOwner;
    }
}