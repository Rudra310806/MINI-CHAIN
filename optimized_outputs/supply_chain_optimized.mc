contract SupplyChain {
    state status : string;
    state owner : address;

    function registerProduct() {
        status = "registered";
    }

    function dispatchProduct() {
        int dispatchCode = (2 * 4);
        require((status == "registered"));
        status = "dispatched";
    }

    function deliverProduct() {
        int deliveryCode = 10;
        require((status == "dispatched"));
        status = "delivered";
    }

    function transferOwnership(new_owner : address) {
        require((owner == new_owner));
        owner = new_owner;
    }
}
