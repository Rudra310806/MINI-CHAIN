contract SupplyChainReviewDemo {
    state status : string;
    state owner : address;
    state shipment_count : int;
    state delivered_count : int;

    function registerShipment(initial_status : string) {
        status = "registered";
        shipment_count = shipment_count + 1;
    }

    function dispatchShipment() {
        status = "dispatched";
        require(status == "registered");
    }

    function dispatchValidShipment() {
        require(status == "registered");
        status = "dispatched";
    }

    function deliverShipment() {
        require(status == "dispatched");
        status = "delivered";
        delivered_count = delivered_count + 1;
    }

    function deliverWithWrongState() {
        require(status == "dispatched");
        status = "in_transit";
    }

    function transferOwnership(new_owner : address) {
        require(owner == new_owner);
        owner = new_owner;
    }

    function registerPackage() {
        status = "pending";
        shipment_count = shipment_count + 1;
    }

    function cancelShipment() {
        require(status == "registered");
        status = "cancelled";
    }

    function markInTransit() {
        require(status == "registered");
        status = "in_transit";
    }

    function completeDelivery() {
        require(status == "dispatched");
        status = "delivered";
        delivered_count = delivered_count + 1;
    }

    function updateOwner(new_owner : address) {
        require(owner == new_owner);
        owner = new_owner;
    }

    function getShipmentCount() : int {
        return shipment_count;
    }

    function getDeliveredCount() : int {
        return delivered_count;
    }

    function inspectStatus() : string {
        return status;
    }

    function dispatchAgain() {
        require(status == "registered");
        status = "shipped";
    }

    function receiveShipment() {
        require(status == "dispatched");
        status = "delivered";
        delivered_count = delivered_count + 1;
    }
}
